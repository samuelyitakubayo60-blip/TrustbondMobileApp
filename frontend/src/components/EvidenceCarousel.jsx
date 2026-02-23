import { useState, useRef, useCallback, useEffect } from 'react';

const SWIPE_THRESHOLD = 60;
const TRANSITION_MS = 280;

export default function EvidenceCarousel({ items }) {
  const evidenceItems = Array.isArray(items) ? items : [];
  const [index, setIndex] = useState(0);
  const [drag, setDrag] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const touchStartX = useRef(0);
  const mouseStartX = useRef(0);

  const total = evidenceItems.length;
  const currentIndex = Math.min(Math.max(index, 0), total - 1);
  const current = evidenceItems[currentIndex];

  const goPrev = useCallback(() => {
    setIndex((i) => (i > 0 ? i - 1 : 0));
  }, []);

  const goNext = useCallback(() => {
    setIndex((i) => (i < total - 1 ? i + 1 : total - 1));
  }, [total]);

  const goTo = useCallback((i) => {
    setIndex(Math.min(Math.max(i, 0), total - 1));
  }, [total]);

  // Keyboard
  useEffect(() => {
    const onKey = (e) => {
      if (!evidenceItems.length) return;
      if (e.key === 'ArrowLeft') goPrev();
      if (e.key === 'ArrowRight') goNext();
      if (e.key === 'Escape') setLightboxOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [evidenceItems.length, goPrev, goNext]);

  const handleTouchStart = (e) => {
    touchStartX.current = e.touches[0].clientX;
    setIsDragging(true);
    setDrag(0);
  };

  const handleTouchMove = (e) => {
    if (!isDragging) return;
    const dx = e.touches[0].clientX - touchStartX.current;
    const max = typeof window !== 'undefined' ? window.innerWidth * 0.4 : 200;
    setDrag(Math.max(-max, Math.min(max, dx)));
  };

  const handleTouchEnd = () => {
    if (!isDragging) return;
    setIsDragging(false);
    if (drag > SWIPE_THRESHOLD && currentIndex > 0) goPrev();
    else if (drag < -SWIPE_THRESHOLD && currentIndex < total - 1) goNext();
    setDrag(0);
  };

  const handleMouseDown = (e) => {
    mouseStartX.current = e.clientX;
    setIsDragging(true);
    setDrag(0);
  };

  const handleMouseMove = (e) => {
    if (!isDragging) return;
    const dx = e.clientX - mouseStartX.current;
    const max = 200;
    setDrag(Math.max(-max, Math.min(max, dx)));
  };

  const handleMouseUp = () => {
    if (!isDragging) return;
    setIsDragging(false);
    if (drag > SWIPE_THRESHOLD && currentIndex > 0) goPrev();
    else if (drag < -SWIPE_THRESHOLD && currentIndex < total - 1) goNext();
    setDrag(0);
  };

  const handleMouseLeave = () => {
    if (isDragging) {
      setIsDragging(false);
      setDrag(0);
    }
  };

  if (!evidenceItems.length) return null;

  const isPhoto = (item) => String(item?.file_type).toLowerCase() === 'photo';

  const SlideContent = ({ item, label }) => (
    <div className="evidence-carousel-slide">
      {isPhoto(item) ? (
        <img src={item.file_url} alt={label} className="evidence-media" loading="lazy" />
      ) : (
        <video src={item.file_url} controls className="evidence-media" />
      )}
    </div>
  );

  const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 400;
  const trackOffset = -(currentIndex * 100) + (total > 0 ? (drag / viewportWidth) * 100 : 0);

  return (
    <div className="evidence-carousel">
      <div
        className="evidence-carousel-viewport"
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onTouchCancel={handleTouchEnd}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
      >
        <div
          className="evidence-carousel-track"
          style={{
            transform: `translate3d(${trackOffset}%, 0, 0)`,
            transition: isDragging ? 'none' : `transform ${TRANSITION_MS}ms cubic-bezier(0.25, 0.46, 0.45, 0.94)`,
            width: `${total * 100}%`,
          }}
        >
          {evidenceItems.map((item, i) => (
            <div key={item.evidence_id || i} className="evidence-carousel-slide-wrap" style={{ width: `${100 / total}%` }}>
              <SlideContent item={item} label={`${isPhoto(item) ? 'Photo' : 'Video'} ${i + 1}`} />
            </div>
          ))}
        </div>

        {total > 1 && (
          <>
            {currentIndex > 0 && (
              <button
                type="button"
                className="evidence-carousel-arrow evidence-carousel-arrow-prev"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); goPrev(); }}
                aria-label="Previous"
              >
                <ChevronLeft />
              </button>
            )}
            {currentIndex < total - 1 && (
              <button
                type="button"
                className="evidence-carousel-arrow evidence-carousel-arrow-next"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); goNext(); }}
                aria-label="Next"
              >
                <ChevronRight />
              </button>
            )}
          </>
        )}

        {total > 1 && (
          <div className="evidence-carousel-dots">
            {evidenceItems.map((_, i) => (
              <button
                key={i}
                type="button"
                className={`evidence-carousel-dot ${i === currentIndex ? 'active' : ''}`}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => goTo(i)}
                aria-label={`Go to ${i + 1} of ${total}`}
              />
            ))}
          </div>
        )}

        <button
          type="button"
          className="evidence-carousel-expand"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={() => setLightboxOpen(true)}
          aria-label="Expand"
        >
          <ExpandIcon />
        </button>
      </div>

      {lightboxOpen && (
        <div
          className="evidence-lightbox-overlay"
          onClick={() => setLightboxOpen(false)}
          role="presentation"
        >
          <div className="evidence-lightbox-inner" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="evidence-lightbox-close"
              onClick={() => setLightboxOpen(false)}
              aria-label="Close"
            >
              <CloseIcon />
            </button>
            {total > 1 && currentIndex > 0 && (
              <button type="button" className="evidence-lightbox-arrow prev" onClick={goPrev} aria-label="Previous">
                <ChevronLeft />
              </button>
            )}
            {total > 1 && currentIndex < total - 1 && (
              <button type="button" className="evidence-lightbox-arrow next" onClick={goNext} aria-label="Next">
                <ChevronRight />
              </button>
            )}
            <div className="evidence-lightbox-media">
              {isPhoto(current) ? (
                <img src={current.file_url} alt="" />
              ) : (
                <video src={current.file_url} controls autoPlay />
              )}
            </div>
            {total > 1 && (
              <div className="evidence-lightbox-dots">
                {evidenceItems.map((_, i) => (
                  <button
                    key={i}
                    type="button"
                    className={i === currentIndex ? 'active' : ''}
                    onClick={() => goTo(i)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ChevronLeft() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15 18l-6-6 6-6" />
    </svg>
  );
}

function ChevronRight() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

function ExpandIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 3H5a2 2 0 00-2 2v3m18 0V5a2 2 0 00-2-2h-3m3 0h3M3 16v3a2 2 0 002 2h3m0-3h3m3-3l3 3-3-3m3-3l-3 3 3 3" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 6L6 18M6 6l12 12" />
    </svg>
  );
}
