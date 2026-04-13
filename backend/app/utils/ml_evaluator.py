#!/usr/bin/env python3

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional, Tuple
from app.database import SessionLocal
from app.models.system_config import SystemConfig
from app.models.report import Report
from app.models.device import Device


class MLEvaluator:
    """ML-based report evaluation service for trust scoring and classification."""
    
    def __init__(self):
        self.config = self._load_ml_config()
    
    def _load_ml_config(self) -> Dict[str, Any]:
        """Load ML configuration from system config."""
        db = SessionLocal()
        try:
            configs = db.query(SystemConfig).filter(
                SystemConfig.config_key.like('ml.%')
            ).all()
            
            config_dict = {}
            for config in configs:
                key = config.config_key.replace('ml.', '')
                if isinstance(config.config_value, dict):
                    config_dict[key] = config.config_value.get('value')
                else:
                    config_dict[key] = config.config_value
            
            # Set defaults if not found
            defaults = {
                'trust_threshold': 70.0,
                'confidence_threshold': 0.7,
                'under_review_threshold': 45.0,
                'auto_verification_threshold': 70.0,
                'max_trust_score': 95.0,
                'min_trust_score': 5.0,
            }
            
            for key, default_value in defaults.items():
                if key not in config_dict:
                    config_dict[key] = default_value
            
            return config_dict
            
        finally:
            db.close()
    
    def evaluate_report(self, report: Report) -> Dict[str, Any]:
        """
        Evaluate a report and return ML prediction with trust score.
        
        Args:
            report: Report object to evaluate
            
        Returns:
            Dict containing:
            - trust_score: Calculated trust score (0-100)
            - prediction_label: 'likely_real', 'suspicious', 'uncertain', or 'fake'
            - confidence: Confidence level (0.0-1.0)
            - reasoning: Explanation of the evaluation
        """
        
        # Base trust score starts at 50%
        trust_score = 50.0
        reasoning_factors = []
        
        # 1. Content Analysis
        content_score, content_reasoning = self._analyze_content(report)
        trust_score += content_score
        reasoning_factors.extend(content_reasoning)
        
        # 2. Location Analysis
        location_score, location_reasoning = self._analyze_location(report)
        trust_score += location_score
        reasoning_factors.extend(location_reasoning)
        
        # 3. Device History Analysis
        device_score, device_reasoning = self._analyze_device_history(report)
        trust_score += device_score
        reasoning_factors.extend(device_reasoning)
        
        # 4. Temporal Analysis
        temporal_score, temporal_reasoning = self._analyze_temporal_patterns(report)
        trust_score += temporal_score
        reasoning_factors.extend(temporal_reasoning)
        
        # Ensure score is within bounds
        trust_score = max(0.0, min(100.0, trust_score))
        
        # Determine prediction label and confidence
        prediction_label, confidence = self._determine_prediction(trust_score, reasoning_factors)
        
        return {
            'trust_score': Decimal(str(trust_score)),
            'prediction_label': prediction_label,
            'confidence': Decimal(str(confidence)),
            'reasoning': '; '.join(reasoning_factors)
        }
    
    def _analyze_content(self, report: Report) -> Tuple[float, list]:
        """Analyze report content for trust signals."""
        score = 0.0
        reasoning = []
        
        if not report.description:
            reasoning.append("No description provided")
            return -10.0, reasoning
        
        description = report.description.lower()
        
        # Check for spam indicators
        spam_patterns = [
            r'(.)\1{4,}',  # Repeated characters
            r'^\s*$',      # Empty or whitespace only
            r'[A-Z]{10,}', # Excessive capitalization
        ]
        
        spam_score = 0
        for pattern in spam_patterns:
            if re.search(pattern, description):
                spam_score += 1
        
        if spam_score > 0:
            score -= spam_score * 15
            reasoning.append(f"Content spam indicators detected: {spam_score}")
        
        # Check for meaningful content length
        word_count = len(description.split())
        if word_count < 3:
            score -= 20
            reasoning.append("Very short description")
        elif word_count > 10:
            score += 10
            reasoning.append("Detailed description provided")
        
        # Check for emergency keywords
        emergency_keywords = ['urgent', 'emergency', 'immediate', 'danger', 'help', 'accident']
        emergency_count = sum(1 for keyword in emergency_keywords if keyword in description)
        if emergency_count > 0:
            score += emergency_count * 5
            reasoning.append(f"Emergency keywords detected: {emergency_count}")
        
        return score, reasoning
    
    def _analyze_location(self, report: Report) -> Tuple[float, list]:
        """Analyze location patterns for trust signals."""
        score = 0.0
        reasoning = []
        
        # Check if coordinates are valid
        if not (report.latitude and report.longitude):
            reasoning.append("Invalid or missing coordinates")
            return -15.0, reasoning
        
        # Basic coordinate validation
        if not (-90 <= report.latitude <= 90 and -180 <= report.longitude <= 180):
            reasoning.append("Invalid coordinate ranges")
            return -20.0, reasoning
        
        # Check for suspicious coordinates (exact zeros, etc.)
        if report.latitude == 0.0 and report.longitude == 0.0:
            reasoning.append("Default coordinates (0,0) - suspicious")
            return -25.0, reasoning
        
        # Reward valid coordinates
        score += 5
        reasoning.append("Valid GPS coordinates provided")
        
        # Check location diversity (simplified)
        db = SessionLocal()
        try:
            recent_reports = db.query(Report).filter(
                Report.device_id == report.device_id,
                Report.reported_at >= datetime.utcnow() - timedelta(days=7)
            ).all()
            
            if len(recent_reports) > 10:
                # Check if all reports are from same location
                locations = [(r.latitude, r.longitude) for r in recent_reports]
                unique_locations = set(locations)
                
                if len(unique_locations) == 1:
                    score -= 10
                    reasoning.append("All reports from same location - suspicious")
                elif len(unique_locations) >= 3:
                    score += 10
                    reasoning.append("Diverse reporting locations")
        
        finally:
            db.close()
        
        return score, reasoning
    
    def _analyze_device_history(self, report: Report) -> Tuple[float, list]:
        """Analyze device reporting history for trust signals."""
        score = 0.0
        reasoning = []
        
        db = SessionLocal()
        try:
            device = db.query(Device).filter(Device.device_id == report.device_id).first()
            
            if not device:
                reasoning.append("Unknown device")
                return -10.0, reasoning
            
            # Use device trust score as base
            device_trust = float(device.device_trust_score) if device.device_trust_score else 50.0
            
            if device_trust >= 80:
                score += 20
                reasoning.append("High device trust score")
            elif device_trust >= 60:
                score += 10
                reasoning.append("Medium device trust score")
            elif device_trust < 40:
                score -= 15
                reasoning.append("Low device trust score")
            
            # Check reporting frequency
            recent_reports = db.query(Report).filter(
                Report.device_id == report.device_id,
                Report.reported_at >= datetime.utcnow() - timedelta(hours=24)
            ).count()
            
            if recent_reports > 20:
                score -= 20
                reasoning.append("Excessive reporting frequency")
            elif recent_reports > 10:
                score -= 10
                reasoning.append("High reporting frequency")
            elif recent_reports <= 5:
                score += 5
                reasoning.append("Normal reporting frequency")
            
            # Check confirmation rate
            if hasattr(device, 'trusted_reports') and hasattr(device, 'total_reports'):
                total = device.total_reports or 1
                confirmed = device.trusted_reports or 0
                confirmation_rate = (confirmed / total) * 100
                
                if confirmation_rate >= 80:
                    score += 15
                    reasoning.append("High confirmation rate")
                elif confirmation_rate >= 60:
                    score += 8
                    reasoning.append("Good confirmation rate")
                elif confirmation_rate < 30:
                    score -= 15
                    reasoning.append("Low confirmation rate")
        
        finally:
            db.close()
        
        return score, reasoning
    
    def _analyze_temporal_patterns(self, report: Report) -> Tuple[float, list]:
        """Analyze temporal patterns for trust signals."""
        score = 0.0
        reasoning = []
        
        # Check reporting time
        report_time = report.reported_at
        
        if not report_time:
            reasoning.append("Missing timestamp")
            return -5.0, reasoning
        
        # Check for unusual reporting hours (simplified)
        hour = report_time.hour
        if hour >= 2 and hour <= 5:  # Very late night/early morning
            score -= 5
            reasoning.append("Reported during unusual hours")
        
        # Check for future timestamps
        if report_time > datetime.utcnow():
            score -= 30
            reasoning.append("Future timestamp - suspicious")
        
        # Check how recent the report is
        time_diff = datetime.utcnow() - report_time
        if time_diff.total_seconds() > 86400:  # More than 24 hours old
            score -= 5
            reasoning.append("Old report")
        
        return score, reasoning
    
    def _determine_prediction(self, trust_score: float, reasoning: list) -> Tuple[str, float]:
        """Determine prediction label and confidence based on trust score."""
        
        # Calculate confidence based on consistency of reasoning
        confidence = 0.7  # Base confidence
        
        # Adjust confidence based on reasoning
        negative_factors = sum(1 for r in reasoning if 'suspicious' in r.lower() or 'spam' in r.lower())
        positive_factors = sum(1 for r in reasoning if 'high' in r.lower() or 'good' in r.lower() or 'valid' in r.lower())
        
        if negative_factors > positive_factors:
            confidence -= 0.2
        elif positive_factors > negative_factors:
            confidence += 0.2
        
        confidence = max(0.3, min(0.95, confidence))
        
        # Determine prediction label - only use allowed values
        if trust_score >= self.config.get('trust_threshold', 70.0):
            return 'likely_real', confidence
        elif trust_score >= self.config.get('under_review_threshold', 45.0):
            return 'suspicious', confidence  # Changed from 'uncertain' to 'suspicious'
        else:
            return 'fake', confidence


# Singleton instance
ml_evaluator = MLEvaluator()
