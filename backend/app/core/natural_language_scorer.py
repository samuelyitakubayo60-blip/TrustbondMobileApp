"""
Natural Language Model Scorer
Analyzes description quality and semantic consistency.
Outputs only scores - no decision making.

Updated for 5-stage pipeline:
- Incident validation now handled by Stage 2 (semantic_incident_validator)
- Description quality now handled by Stage 3 (description_quality_analyzer)
- This module provides backward-compatible interface for callers
  that still use analyze_description_quality()
- Keyword matching REMOVED — semantic analysis used instead
"""

from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

from .trust_thresholds import trust_thresholds

logger = logging.getLogger(__name__)


# ── Incident reference texts REMOVED ─────────────────────────────────────────
# Keyword matching has been completely replaced by semantic embeddings
# and LLM reasoning in Stage 2 (semantic_incident_validator.py).
# These reference texts are kept ONLY as fallback for the legacy TF-IDF path
# when sentence-transformers AND LLM APIs are both unavailable.

_INCIDENT_REFERENCE_TEXTS: Dict[str, str] = {
    # ── Property crimes ───────────────────────────────────────────────────────
    "theft": (
        "someone stole took snatched grabbed robbed my phone mobile smartphone laptop "
        "computer tablet bag backpack handbag purse wallet cash money valuables jewelry "
        "necklace bracelet watch ring bicycle bike moto motorcycle motorbike car vehicle "
        "truck minibus bus cattle cow bull heifer goat sheep pig chicken poultry crops "
        "harvest Irish potato beans maize sorghum banana cassava radio television TV "
        "tools equipment generator solar panel door window lock broken missing property "
        "thief thieves pickpocket ran away fled market bus station road street night "
        "while away house home entered break broke in steal stealing theft larceny "
        "boda boda piki piki moto taxi two wheeler "
        "vole volé voleur téléphone portefeuille sac "
        "ibyibuye imodoka igare telefoni imfashanyo amafaranga "
    ),
    "robbery": (
        "armed robbery robber attack threatened forced demand money phone bag valuables "
        "gun pistol firearm knife machete sword weapon held at gunpoint knifepoint "
        "grabbed snatched violent mugged mugging purse snatching highway robbery "
        "masked gang group two three four men road street night dark alley market "
        "gave up handed over beat hit punched kicked injured wounded ran away fled moto "
        "motorcycle car vehicle ambush surprise attack forced surrender "
        "vol à main armée voleur armé arme couteau pistolet "
        "gutunga intwaro inzira gutwara imodoka "
    ),
    "burglary": (
        "broke broken entered forced open door window lock house home apartment shop "
        "store warehouse farm building while away at night sleeping work market "
        "stolen missing valuables electronics phone laptop money cash jewelry tools "
        "furniture appliances left sign entry footprints broken glass forced entry "
        "burglar intruder trespassed searched ransacked went through everything "
        "cambriolage effraction maison domicile "
        "kunyaga inzu gutunika ikirisho "
    ),
    "pickpocket": (
        "pickpocket pocket stolen phone wallet money cash market bus station crowd "
        "transport public place while moving walking distracted bumped shoulder bag "
        "snatched grabbed did not notice until gone missing handbag purse pocket "
        "crowded area bus stand taxi park market stall "
    ),
    "larceny": (
        "stolen property took missing valuables household items equipment tools "
        "unattended left outside yard farm field market store "
    ),
    # ── Violent crimes ────────────────────────────────────────────────────────
    "assault": (
        "assault attacked beat beaten hit punched kicked slapped pushed shoved "
        "weapon knife stick stone rod iron bar club machete physically injured "
        "wounded bruised bleeding hospital treatment bodily harm fight argument "
        "provoked without reason came from behind group people stranger road "
        "market night bus station injured hurt head face arm leg ribs "
        "agression attaque frappé blessé "
        "gutera gutunga gukubita igikonjo inkota inkoni "
    ),
    "attack": (
        "attacked assaulted beaten hit punched kicked weapon knife machete stick "
        "stone iron bar ambush surprise came behind group gang injured wounded "
        "road night dark alley market area neighbourhood "
    ),
    "fight": (
        "fight fighting brawl argument dispute quarrel hit punch kick beat group "
        "gang several people conflict rivalry drunk alcohol bar pub entertainment "
        "night public place market noise screaming shouting help "
    ),
    "stabbing": (
        "stabbed stab knife blade sharp object cut wound deep gash bleeding blood "
        "injury severe hospital emergency rushed operated machete sword broken bottle "
        "glass neck chest abdomen arm leg serious life threatening "
    ),
    "beating": (
        "beaten beat hit punch kick batter bludgeon stick rod iron pipe club stone "
        "hands fists severe seriously injured multiple wounds bruises swelling blood "
        "unconscious hospital emergency gang group multiple attackers "
    ),
    "violence": (
        "violence violent attack beat hit injure wound weapon knife gun stick "
        "machete physically harmed threatened life bodily harm serious dangerous "
    ),
    "murder": (
        "killed murder dead death body corpse found weapon knife gun shot stabbed "
        "blood injuries fatal severe critical no signs life passed away homicide "
        "crime scene discovered reported police "
    ),
    "homicide": (
        "killed dead murder homicide body found no signs of life fatal injuries "
        "shot stabbed attacked brutally weapon scene crime report "
    ),
    "kidnap": (
        "kidnapped abducted taken away missing person forced into car vehicle "
        "disappeared unknown location held captive ransom demand family "
        "last seen stranger group vehicle moto motorcycle took away "
    ),
    "abduction": (
        "abducted kidnapped taken missing forced vehicle unknown location "
        "disappeared last seen child woman person group men stranger "
    ),
    # ── Domestic / family ─────────────────────────────────────────────────────
    "domestic": (
        "husband wife spouse partner boyfriend girlfriend family member home house "
        "domestic violence beating hit punched kicked slapped threatened weapon "
        "children scared fear injuries abuse repeated ongoing argument quarrel "
        "locked out fled neighbours heard screams called police "
        "violence domestique conjoint époux épouse "
        "umuryango inzu gutera umugabo umugore "
    ),
    "defilement": (
        "defilement minor child underage girl boy sexually assaulted abused "
        "inappropriate touching forced violated rape victim young age school "
        "neighbour family member relative stranger "
    ),
    # ── Sexual crimes ─────────────────────────────────────----------------------------------------------------------------
    "rape": (
        "raped rape sexual assault forced intercourse violated victim injured "
        "traumatised hospital examination evidence clothing torn injuries "
        "perpetrator known unknown neighbour relative stranger "
    ),
    "sexual": (
        "sexually assaulted harassed touched inappropriately forced indecent act "
        "rape victim injuries trauma hospital evidence "
    ),
    "indecent": (
        "indecent exposure naked inappropriate sexual behaviour public place "
        "exposed genitals lewd conduct children witnesses "
    ),
    # ── Public order ──────────────────────────────────────────────────────────
    "harassment": (
        "harassed harassment threatened repeatedly following stalking intimidating "
        "abusive language insults threats online phone calls messages blocking path "
        "workplace neighbour ex partner frightened scared fear "
    ),
    "threat": (
        "threatened threaten verbal threat weapon knife machete gun dangerous "
        "will harm kill hurt property fear scared witnesses "
    ),
    "disturbance": (
        "disturbing disturbance noise loud shouting screaming drunk intoxicated "
        "fighting group people public place night neighbours calling police "
    ),
    "noise": (
        "noise loud music shouting disturbance neighbour night residential area "
        "repeated warnings ignored annoying disruptive "
    ),
    "riot": (
        "riot crowd mob group stone throwing burning property looting destruction "
        "violence chaos disorder public place confrontation police "
    ),
    # ── Drug / substance ─────────────────────────────────────────────────────
    "drug": (
        "drugs drug dealing selling buying using consuming substances illegal "
        "cannabis marijuana weed heroin cocaine crack pills tablets injection "
        "syringe dealer pusher transaction exchange package pocket area known "
        "youth neighbourhood school vicinity suspicious activity "
        "drogue trafic stupéfiant cannabis cocaïne "
        "inzoga ibiyobyabwenge gucuruza "
    ),
    "narcotic": (
        "narcotics illegal substances drugs dealing possession trafficking "
        "pills tablets powder injection suspicious package exchange money "
    ),
    "cannabis": (
        "cannabis marijuana weed ganja smoking dealing selling using growing "
        "plantation cultivation hidden suspicious smell "
    ),
    "alcohol": (
        "drunk intoxicated alcohol drinking beer wine spirits excessively public "
        "fighting disturbance staggering abusive language causing trouble "
        "bar pub roadside kiosk illegal brew "
    ),
    # ── Financial crimes ──────────────────────────────────────────────────────
    "fraud": (
        "fraud scam deceived tricked false pretence money transfer mobile money "
        "mobile banking fake promise investment business deal cheated lost money "
        "impersonation false identity documents fake goods counterfeit currency "
        "arnaque escroquerie tromperie argent "
    ),
    "scam": (
        "scam fraud tricked deceived promised money investment fake goods "
        "never delivered disappeared with money cheated lost cash "
    ),
    "forgery": (
        "forged fake false document identity card national ID passport certificate "
        "degree diploma land title ownership deed counterfeit "
    ),
    "extortion": (
        "extortion blackmail threatening demanding money pay or else harm hurt "
        "expose information personal intimate photos videos coercion "
    ),
    "bribery": (
        "bribe bribery corrupt official demanded money payment service clearance "
        "permit license document processing informal payment "
    ),
    "corruption": (
        "corruption corrupt official abuse power demand bribe money payment "
        "service delayed blocked favour exchange public office "
    ),
    # ── Traffic / road ────────────────────────────────────────────────────────
    "traffic": (
        "traffic accident crash collision vehicle car truck bus minibus motorcycle "
        "moto bicycle pedestrian road highway junction roundabout hit ran over "
        "injured wounded killed serious minor damage property reckless speeding "
        "overtaking drunk driving no licence no insurance "
        "accident de circulation voiture moto collision "
        "impanuka imodoka igare umuhanda "
    ),
    "road": (
        "road accident crash collision vehicle hit injured road surface hazard "
        "dangerous condition pothole debris obstruction "
    ),
    "accident": (
        "accident crash collision hit knocked ran over vehicle car truck moto "
        "bicycle pedestrian injured wounded dead serious damage road "
    ),
    "reckless": (
        "reckless driving speeding dangerous overtaking wrong lane drunk driving "
        "running red light no brake light near miss almost accident "
    ),
    # ── Environmental / disaster ──────────────────────────────────────────────
    "fire": (
        "fire burning flames smoke house building shop market crop field "
        "electrical fault candle gas cooker arson deliberate set alight "
        "spread fast neighbours evacuated property damage casualties "
        "incendie feu brûlé flammes "
        "umuriro gutunga gusiga "
    ),
    "arson": (
        "arson deliberately set fire intentional burning building house property "
        "crop field vehicle suspected motive revenge dispute "
    ),
    "flood": (
        "flood flooding water overflow river stream rain heavy downpour "
        "road blocked house submerged crops destroyed livestock killed displaced "
    ),
    "landslide": (
        "landslide mudslide slope collapse hill heavy rain debris mud rock "
        "buried house infrastructure road blocked casualties "
    ),
    # ── Suspicious / surveillance ─────────────────────────────────────────────
    "suspicious": (
        "suspicious activity person behaviour strange unfamiliar lurking watching "
        "following observing circling hiding loitering area checking houses "
        "vehicles unknown group night dark "
    ),
    "vandalism": (
        "vandalism damage destroy damaged smashed broken graffiti spray paint "
        "defaced property wall fence vehicle tyres slashed windows broken "
        "deliberate malicious wanton destruction "
    ),
    "trespass": (
        "trespassing entered without permission property land farm field fence "
        "boundary crossed unauthorized access warning ignored "
    ),
    "loitering": (
        "loitering hanging around standing group area no apparent reason "
        "suspicious behaviour watching neighbourhood concern "
    ),
    # ── Wildlife / environmental crime ────────────────────────────────────────
    "poach": (
        "poaching illegal hunting wildlife animal park forest snare trap "
        "killed captured sold trade endangered species "
    ),
    "environmental": (
        "illegal logging deforestation cutting trees protected forest "
        "illegal mining quarrying environmental damage "
    ),
}


def _find_incident_reference_text(incident_type_lower: str) -> str:
    """Return the richest reference text for an incident type by substring match.

    Multiple keys can match (e.g. 'armed robbery' matches both 'rob' and 'robbery');
    all matching texts are concatenated so none of the vocabulary is lost.
    """
    parts: List[str] = []
    for key, text in _INCIDENT_REFERENCE_TEXTS.items():
        if key in incident_type_lower:
            parts.append(text)
    return " ".join(parts).strip()


@dataclass
class NLAnalysisResult:
    """Result of natural language analysis."""
    description_quality_score: float  # 0-100
    semantic_similarity_score: float  # 0-100
    overall_score: float  # 0-100 weighted combination
    confidence: float  # 0.0-1.0
    metadata: Dict[str, Any]

class NaturalLanguageScorer:
    """Natural language model scorer for description analysis."""
    
    def __init__(self):
        self.thresholds = trust_thresholds
    
    def analyze_description(
        self,
        description: str,
        incident_type_name: str,
        incident_type_description: str = ""
    ) -> NLAnalysisResult:
        """
        Analyze description quality and semantic consistency.
        
        Args:
            description: Report description text
            incident_type_name: Name of the incident type
            incident_type_description: Description of the incident type
            
        Returns:
            NLAnalysisResult with scores and metadata
        """
        if not description or not description.strip():
            return self._create_empty_result("No description provided")
        
        description = description.strip()
        
        # 1. Description Quality Analysis
        quality_score, quality_metadata = self._analyze_description_quality(description)
        
        # 2. Semantic Consistency Analysis
        semantic_score, semantic_metadata = self._analyze_semantic_consistency(
            description, incident_type_name, incident_type_description
        )
        
        # 3. Calculate overall score (weighted combination)
        overall_score = (quality_score * 0.6) + (semantic_score * 0.4)
        
        # 4. Calculate confidence based on analysis completeness
        confidence = self._calculate_confidence(quality_metadata, semantic_metadata)
        
        # 5. Create result
        metadata = {
            "description_length": len(description),
            "word_count": len(description.split()),
            "quality_analysis": quality_metadata,
            "semantic_analysis": semantic_metadata,
            "incident_type": incident_type_name,
            "analyzed_at": datetime.now(timezone.utc).isoformat()
        }
        
        return NLAnalysisResult(
            description_quality_score=quality_score,
            semantic_similarity_score=semantic_score,
            overall_score=overall_score,
            confidence=confidence,
            metadata=metadata
        )
    
    def _analyze_description_quality(self, description: str) -> Tuple[float, Dict[str, Any]]:
        """Analyze description quality (length, readability, meaningful content)."""
        score = 0.0
        metadata = {}
        
        # Length analysis
        length = len(description)
        word_count = len(description.split())
        
        if length >= self.thresholds.config.DESCRIPTION_ADEQUATE_LENGTH:
            score += 30
            metadata["length_score"] = "adequate"
        elif length >= self.thresholds.config.DESCRIPTION_MIN_LENGTH:
            score += 15
            metadata["length_score"] = "minimal"
        else:
            metadata["length_score"] = "insufficient"
        
        # Word count analysis (15+ words recommended for full credit)
        min_words = getattr(self.thresholds.config, "DESCRIPTION_MIN_WORDS", 15)
        if word_count >= min_words + 10:
            score += 25
            metadata["word_count_score"] = "detailed"
        elif word_count >= min_words:
            score += 18
            metadata["word_count_score"] = "adequate"
        elif word_count >= max(5, min_words // 2):
            score += 8
            metadata["word_count_score"] = "moderate"
        else:
            metadata["word_count_score"] = "minimal"
        
        # Meaningful content analysis
        meaningful_score = self._analyze_meaningful_content(description)
        score += meaningful_score * 25
        metadata["meaningful_content_score"] = meaningful_score * 25
        
        # Spam/gibberish detection
        spam_penalty = self._detect_spam_indicators(description)
        score -= spam_penalty
        metadata["spam_penalty"] = spam_penalty
        
        # Emergency keywords (positive signal)
        emergency_bonus = self._detect_emergency_keywords(description)
        score += emergency_bonus
        metadata["emergency_bonus"] = emergency_bonus
        
        # Clamp to 0-100
        score = max(0.0, min(100.0, score))
        
        metadata["final_quality_score"] = score
        
        return score, metadata
    
    def _analyze_semantic_consistency(
        self,
        description: str,
        incident_type_name: str,
        incident_type_description: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Analyze semantic consistency between description and incident type.

        Now delegates to the semantic pipeline (Stage 2) when possible,
        falling back to LLM API or TF-IDF for backward compatibility.
        Keyword matching has been completely removed.
        """
        metadata = {
            "incident_type": incident_type_name,
            "semantic_model_available": False
        }

        # Primary path: use semantic embeddings from Stage 2 module
        try:
            from app.core.semantic_incident_validator import compute_embedding_similarity
            semantic_def = f"{incident_type_name}: {incident_type_description}" if incident_type_description else incident_type_name
            emb_score = compute_embedding_similarity(description, semantic_def)
            if emb_score > 0:
                metadata.update({
                    "scoring_method": "semantic_embedding",
                    "semantic_model_available": True,
                    "embedding_similarity": emb_score,
                })
                return emb_score, metadata
        except Exception as exc:
            logger.debug("Semantic embedding fallback: %s", exc)

        from app.config import settings

        # Secondary: LLM API
        if getattr(settings, "enable_semantic_match", False) and report_semantic_llm_configured():
            api_score, api_meta = score_description_incident_similarity(
                description,
                incident_type_name,
                incident_type_description,
            )
            if api_score is not None:
                metadata.update(api_meta)
                return float(api_score), metadata

        # Tertiary: TF-IDF fallback (no keyword matching)
        tfidf_score, tfidf_meta = self._tfidf_consistency(description, incident_type_name, metadata)
        if tfidf_meta.get("scoring_method") == "tfidf":
            return tfidf_score, tfidf_meta

        # Last resort: neutral score (no keyword matching)
        metadata["scoring_method"] = "neutral_fallback"
        return 50.0, metadata
    
    def _tfidf_consistency(
        self,
        description: str,
        incident_type_name: str,
        metadata: Dict[str, Any],
    ) -> Tuple[float, Dict[str, Any]]:
        """TF-IDF cosine similarity between description and a rich incident reference text.

        This is far more robust than substring keyword matching because:
        - Handles all word forms (steal/stole/stolen via term overlap)
        - Handles any object type (phone, motorcycle, car, cattle, laptop…)
        - Handles partial vocabulary overlap naturally
        - Works on description length and vocabulary diversity, not exact keywords

        Falls back gracefully if scikit-learn raises an error.
        """
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity as _cosine_sim
        except ImportError:
            return 35.0, {**metadata, "scoring_method": "tfidf_unavailable"}

        incident_type_lower = incident_type_name.lower()
        ref_text = _find_incident_reference_text(incident_type_lower)
        if not ref_text:
            # Unknown incident type — derive reference from the type name itself
            ref_text = incident_type_lower.replace("_", " ").replace("-", " ")

        try:
            vectorizer = TfidfVectorizer(
                analyzer="word",
                ngram_range=(1, 2),
                min_df=1,
                sublinear_tf=True,
            )
            tfidf = vectorizer.fit_transform([description.lower(), ref_text.lower()])
            sim = float(_cosine_sim(tfidf[0:1], tfidf[1:2])[0][0])
        except Exception as exc:
            logger.debug("TF-IDF scoring failed: %s", exc)
            return 35.0, {**metadata, "scoring_method": "tfidf_error", "error": str(exc)}

        # Map 0-1 cosine similarity → 0-100 score.
        # Empirical calibration against real incident descriptions:
        #   clear match (English)  → sim ≈ 0.04-0.08  → score 55-95
        #   non-English (Kinyarwanda/French) → sim ≈ 0.01 → score ~25 (neutral)
        #   completely unrelated   → sim ≈ 0.005-0.008 → score ~20  (weak signal)
        # Formula: sim * 1000 + 15 provides better spread across realistic reports.
        score = round(min(100.0, max(10.0, sim * 1000.0 + 15.0)), 2)
        metadata.update(
            {
                "scoring_method": "tfidf",
                "tfidf_cosine_similarity": round(sim, 4),
                "keyword_score": score,
                "keyword_match_type": "tfidf_cosine",
            }
        )
        return score, metadata

    def _keyword_based_consistency(
        self,
        description: str,
        incident_type_name: str,
        metadata: Dict[str, Any],
    ) -> Tuple[float, Dict[str, Any]]:
        """Last-resort keyword fallback when TF-IDF is unavailable.

        Keys are substrings matched against the incident type name.
        Zero matches returns 30 (neutral) so descriptions in non-English
        languages are not penalised just because our keyword list is English.
        """
        description_lower = description.lower()
        incident_type_lower = incident_type_name.lower()

        # Build keyword set from the same reference vocabulary used by TF-IDF.
        ref_text = _find_incident_reference_text(incident_type_lower)
        if ref_text:
            relevant_keywords: set = {
                w for w in re.findall(r"[a-z]{3,}", ref_text.lower())
            }
            matched_key = incident_type_lower
        else:
            # Unknown incident type — derive from name tokens
            stopwords = {
                "incident", "activity", "case", "report", "event", "type",
                "and", "or", "the", "of", "in", "at", "to",
            }
            relevant_keywords = {
                tok for tok in re.findall(r"[a-z]{4,}", incident_type_lower)
                if tok not in stopwords
            }
            matched_key = None

        if not relevant_keywords:
            metadata.update({
                "keyword_match_type": "no_specific_keywords",
                "matched_keywords": [],
                "keyword_score": 35.0,
            })
            return 35.0, metadata

        matched_keywords = [kw for kw in relevant_keywords if kw in description_lower]
        match_count = len(matched_keywords)

        if match_count >= 5:
            score = 90.0
        elif match_count >= 4:
            score = 80.0
        elif match_count >= 3:
            score = 70.0
        elif match_count >= 2:
            score = 60.0
        elif match_count >= 1:
            score = 48.0
        else:
            # 30 = neutral, not a strong mismatch signal.
            # Non-English descriptions will get 0 keyword matches but should
            # NOT be automatically flagged as mismatches.
            score = 30.0

        metadata.update({
            "scoring_method": "keyword_fallback",
            "keyword_match_type": "keyword_based",
            "matched_incident_key": matched_key,
            "matched_keywords": matched_keywords[:20],
            "match_count": match_count,
            "keyword_score": score,
        })
        return score, metadata
    
    def _analyze_meaningful_content(self, description: str) -> float:
        """Analyze if description contains meaningful content."""
        score = 0.0
        
        # Check for alphabetic content
        letters = re.findall(r"[a-zA-Z]", description)
        if letters:
            alpha_ratio = len(letters) / len(description)
            if alpha_ratio >= 0.7:
                score += 0.8
            elif alpha_ratio >= 0.5:
                score += 0.5
        
        # Check for word diversity
        words = description.lower().split()
        if words:
            unique_words = set(words)
            diversity_ratio = len(unique_words) / len(words)
            if diversity_ratio >= 0.8:
                score += 0.2
            elif diversity_ratio >= 0.6:
                score += 0.1
        
        return score
    
    def _detect_spam_indicators(self, description: str) -> float:
        """Detect spam/gibberish indicators and return penalty score."""
        penalty = 0.0
        
        # Excessive repeated characters
        if re.search(r"(.)\1{6,}", description):
            penalty += 20
        
        # Very long single word (keysmash)
        words = description.split()
        if words and len(max(words, key=len)) >= 18:
            penalty += 15
        
        # Low vowel ratio
        letters = re.findall(r"[a-zA-Z]", description)
        if letters:
            vowels = sum(1 for ch in letters if ch.lower() in "aeiou")
            vowel_ratio = vowels / len(letters)
            if vowel_ratio < 0.18:
                penalty += 10
        
        # Excessive unique characters with few spaces
        unique_chars = len(set(description.lower()))
        if unique_chars >= 22 and description.count(" ") <= 1 and len(description) >= 20:
            penalty += 15
        
        return penalty
    
    def _detect_emergency_keywords(self, description: str) -> float:
        """Detect emergency keywords and return bonus score."""
        emergency_keywords = [
            "urgent", "emergency", "immediate", "danger", "help", 
            "accident", "injured", "bleeding", "fire", "weapon"
        ]
        
        description_lower = description.lower()
        matches = sum(1 for keyword in emergency_keywords if keyword in description_lower)
        
        return min(matches * 3, 15)  # Cap at 15 points
    
    def _calculate_confidence(
        self,
        quality_metadata: Dict[str, Any],
        semantic_metadata: Dict[str, Any]
    ) -> float:
        """Calculate confidence in the analysis."""
        confidence = 0.7  # Base confidence
        
        # Boost confidence if semantic model was available
        if semantic_metadata.get("semantic_model_available", False):
            confidence += 0.2
        
        # Reduce confidence if spam indicators detected
        spam_penalty = quality_metadata.get("spam_penalty", 0)
        if spam_penalty > 10:
            confidence -= 0.2
        
        # Adjust based on description quality
        quality_score = quality_metadata.get("final_quality_score", 0)
        if quality_score >= 70:
            confidence += 0.1
        elif quality_score < 30:
            confidence -= 0.2
        
        return max(0.3, min(1.0, confidence))
    
    def _create_empty_result(self, reason: str) -> NLAnalysisResult:
        """Create empty result for cases where analysis cannot be performed."""
        return NLAnalysisResult(
            description_quality_score=0.0,
            semantic_similarity_score=0.0,
            overall_score=0.0,
            confidence=0.0,
            metadata={
                "error": reason,
                "analyzed_at": datetime.now(timezone.utc).isoformat()
            }
        )


# ── Report semantic checks (Groq/Gemini API — replaces all-MiniLM-L6-v2) ─────

_REPORT_SEMANTIC_CACHE: Dict[str, Any] = {}
_REPORT_SEMANTIC_CACHE_MAX = 512
_REPORT_SEMANTIC_PROVIDER = "groq-gemini-api"
_report_groq_skip: Optional[str] = None
_report_gemini_skip: Optional[str] = None
_report_groq_skip_logged = False
_report_gemini_skip_logged = False


def report_semantic_llm_configured() -> bool:
    has_groq = bool(os.getenv("GROQ_API_KEY", "").strip()) and _report_groq_skip is None
    has_gemini = bool(os.getenv("GEMINI_API_KEY", "").strip()) and _report_gemini_skip is None
    return has_groq or has_gemini


def _report_gemini_model_name() -> str:
    return (os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip() or "gemini-2.0-flash"


def _call_report_semantic_llm(prompt: str, *, max_tokens: int = 300) -> Optional[Dict[str, Any]]:
    global _report_groq_skip, _report_gemini_skip
    global _report_groq_skip_logged, _report_gemini_skip_logged

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if api_key and _report_groq_skip is None:
        try:
            from groq import Groq

            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as exc:
            err = str(exc).lower()
            if "organization_restricted" in err or "invalid_api_key" in err:
                _report_groq_skip = str(exc)[:240]
                if not _report_groq_skip_logged:
                    logger.info(
                        "Groq report semantic LLM disabled: %s",
                        _report_groq_skip,
                    )
                    _report_groq_skip_logged = True
            else:
                logger.warning("Groq report semantic call failed: %s", exc)

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key and _report_gemini_skip is None:
        from app.core.llm_recommendations import _gemini_model_candidates, gemini_generate_json

        for model_name in _gemini_model_candidates():
            parsed = gemini_generate_json(
                prompt,
                gemini_key,
                model_name,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            if parsed:
                return parsed
        _report_gemini_skip = "Gemini returned no valid JSON for any model"
        if not _report_gemini_skip_logged:
            logger.warning("%s", _report_gemini_skip)
            _report_gemini_skip_logged = True
    return None


def _report_semantic_cache_key(prefix: str, payload: str) -> str:
    digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _report_semantic_cache_get(key: str) -> Optional[Any]:
    return _REPORT_SEMANTIC_CACHE.get(key)


def _report_semantic_cache_set(key: str, value: Any) -> None:
    if len(_REPORT_SEMANTIC_CACHE) >= _REPORT_SEMANTIC_CACHE_MAX:
        _REPORT_SEMANTIC_CACHE.clear()
    _REPORT_SEMANTIC_CACHE[key] = value


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def score_description_incident_similarity(
    description: str,
    incident_type_name: str,
    incident_type_description: str = "",
) -> Tuple[Optional[float], Dict[str, Any]]:
    """Semantic similarity 0–100 (description vs incident type). None if no API key."""
    desc = (description or "").strip()
    incident_text = f"{(incident_type_name or '').strip()}: {(incident_type_description or '').strip()}".strip(
        ": "
    )
    meta: Dict[str, Any] = {
        "provider": _REPORT_SEMANTIC_PROVIDER,
        "semantic_model_available": False,
        "incident_type": incident_type_name,
    }
    if len(desc) < 8 or not incident_type_name:
        return 50.0, meta
    if not report_semantic_llm_configured():
        return None, meta

    ck = _report_semantic_cache_key("desc_inc", json.dumps([desc, incident_text], ensure_ascii=False))
    cached = _report_semantic_cache_get(ck)
    if isinstance(cached, dict) and "score" in cached:
        return float(cached["score"]), {**meta, **cached.get("meta", {}), "cached": True}

    prompt = f"""You are validating citizen crime reports for Rwanda National Police (Musanze).

Compare the REPORT DESCRIPTION to the EXPECTED INCIDENT TYPE wording.
Return JSON only:
{{
  "similarity": <float 0.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "brief_reason": "<one short sentence>"
}}

REPORT DESCRIPTION:
{desc[:2000]}

EXPECTED INCIDENT TYPE:
{incident_text[:800]}
"""
    result = _call_report_semantic_llm(prompt, max_tokens=180)
    if not isinstance(result, dict):
        return None, meta

    try:
        sim = _clamp01(float(result.get("similarity", 0.5)))
        conf = _clamp01(float(result.get("confidence", 0.7)))
    except (TypeError, ValueError):
        return None, meta

    score = round(sim * 100.0, 2)
    meta.update(
        {
            "semantic_model_available": True,
            "semantic_similarity": sim,
            "similarity_score": score,
            "confidence": conf,
            "incident_text": incident_text,
            "brief_reason": str(result.get("brief_reason") or "")[:300],
            "model": "llama-3.3-70b-versatile",
        }
    )
    _report_semantic_cache_set(ck, {"score": score, "meta": meta})
    return score, meta


def check_triple_semantic_alignment(
    *,
    report_description: str,
    incident_type_name: str,
    incident_type_description: str,
    evidence_semantic_text: str,
) -> Optional[Dict[str, Any]]:
    """Compare description vs evidence vs incident type via Groq/Gemini."""
    desc = (report_description or "").strip()
    evidence = (evidence_semantic_text or "").strip()
    if len(desc) < 10 or len(evidence) < 10 or not report_semantic_llm_configured():
        return None

    incident_text = (
        f"{(incident_type_name or '').strip()}: {(incident_type_description or '').strip()}"
    ).strip(": ")

    ck = _report_semantic_cache_key(
        "triple",
        json.dumps([desc, evidence, incident_text], ensure_ascii=False),
    )
    cached = _report_semantic_cache_get(ck)
    if isinstance(cached, dict) and "mismatch" in cached:
        return dict(cached)

    prompt = f"""You are validating a citizen crime report for Rwanda National Police.

Score how aligned three texts are (0.0 = unrelated, 1.0 = strongly aligned).
Return JSON only:
{{
  "description_evidence_similarity": <float 0-1>,
  "incident_evidence_similarity": <float 0-1>,
  "description_incident_similarity": <float 0-1>,
  "mismatch": <boolean>
}}

REPORT DESCRIPTION:
{desc[:1500]}

EVIDENCE SUMMARY:
{evidence[:1500]}

INCIDENT TYPE:
{incident_text[:600]}
"""
    result = _call_report_semantic_llm(prompt, max_tokens=220)
    if not isinstance(result, dict):
        return None

    try:
        de = _clamp01(float(result.get("description_evidence_similarity", 0.5)))
        ie = _clamp01(float(result.get("incident_evidence_similarity", 0.5)))
        di = _clamp01(float(result.get("description_incident_similarity", 0.5)))
        mismatch = bool(result.get("mismatch", False))
    except (TypeError, ValueError):
        return None

    if de < 0.32 and ie < 0.34 and di < 0.38:
        mismatch = True

    out = {
        "model": _REPORT_SEMANTIC_PROVIDER,
        "description_evidence_similarity": round(de, 4),
        "incident_evidence_similarity": round(ie, 4),
        "description_incident_similarity": round(di, 4),
        "mismatch": mismatch,
    }
    _report_semantic_cache_set(ck, out)
    return out


def incident_description_mismatch_via_llm(
    description: str,
    selected_incident_type_id: Any,
    incident_types: List[Tuple[Any, str]],
) -> bool:
    """True when another incident type fits the description better than the selected one."""
    desc = (description or "").strip()
    if len(desc) < 12 or len(incident_types) < 2 or not report_semantic_llm_configured():
        return False

    lines = [f'- id="{iid}": {label[:200]}' for iid, label in incident_types[:40]]
    types_block = "\n".join(lines)

    prompt = f"""A citizen picked one incident type but wrote a free-text description.

Return JSON only:
{{
  "best_match_id": "<id from list>",
  "best_match_score": <float 0-1>,
  "selected_match_score": <float 0-1 for id "{selected_incident_type_id}">>,
  "mismatch": <true if different id is clearly better, best_match_score >= 0.42, margin >= 0.10>
}}

DESCRIPTION:
{desc[:2000]}

INCIDENT TYPES:
{types_block}

SELECTED ID: {selected_incident_type_id}
"""
    result = _call_report_semantic_llm(prompt, max_tokens=200)
    if not isinstance(result, dict):
        return False

    try:
        best_id = str(result.get("best_match_id", "")).strip()
        best_score = float(result.get("best_match_score", 0))
        selected_score = float(result.get("selected_match_score", 0))
        mismatch_flag = bool(result.get("mismatch", False))
    except (TypeError, ValueError):
        return False

    if mismatch_flag:
        return True
    return (
        bool(best_id)
        and str(best_id) != str(selected_incident_type_id)
        and best_score >= 0.42
        and (best_score - selected_score) >= 0.10
    )


def warmup_report_semantic_llm() -> bool:
    """Startup: confirm API keys and that google-genai is installed."""
    from app.core.llm_recommendations import verify_google_genai_installed

    if not report_semantic_llm_configured():
        logger.info(
            "Report semantic LLM: no GROQ/GEMINI key — keyword fallbacks for text matching"
        )
        return False
    if os.getenv("GEMINI_API_KEY", "").strip():
        if verify_google_genai_installed():
            logger.info("Gemini SDK ready (google-genai package installed)")
        else:
            logger.error(
                "GEMINI_API_KEY is set but google-genai is not installed. "
                "Add google-genai to requirements.txt and redeploy."
            )
            return False
    if os.getenv("GROQ_API_KEY", "").strip() and os.getenv(
        "HOTSPOT_SKIP_GROQ", ""
    ).strip().lower() not in ("1", "true", "yes"):
        logger.info("Groq API key present (used when Gemini unavailable)")
    logger.info("Report semantic LLM ready")
    return True


# Global instance
natural_language_scorer = NaturalLanguageScorer()

# Export main function for easy access
def analyze_description_quality(
    description: str,
    incident_type_name: str,
    incident_type_description: str = ""
) -> NLAnalysisResult:
    """Convenience function for natural language analysis."""
    return natural_language_scorer.analyze_description(
        description=description,
        incident_type_name=incident_type_name,
        incident_type_description=incident_type_description
    )
