import React from 'react';

/**
 * Renders a table skeleton with animated shimmer rows.
 * Drop-in replacement for the loading state inside any tbl-wrap table.
 *
 * Props:
 *   cols   — number of columns (default 5)
 *   rows   — number of skeleton rows (default 6)
 */
const SkeletonTable = ({ cols = 5, rows = 6 }) => (
  <>
    <style>{`
      @keyframes tb-shimmer {
        0%   { background-position: -400px 0; }
        100% { background-position:  400px 0; }
      }
      .tb-skel {
        display: inline-block;
        border-radius: 4px;
        background: linear-gradient(
          90deg,
          var(--border) 25%,
          var(--surface2) 50%,
          var(--border) 75%
        );
        background-size: 800px 100%;
        animation: tb-shimmer 1.4s ease-in-out infinite;
      }
    `}</style>
    {Array.from({ length: rows }).map((_, r) => (
      <tr key={r} style={{ opacity: 1 - r * (0.6 / rows) }}>
        {Array.from({ length: cols }).map((_, c) => (
          <td key={c} style={{ padding: '10px 12px' }}>
            <span
              className="tb-skel"
              style={{
                height: 12,
                width: c === 0 ? 28 : c === cols - 1 ? 64 : `${55 + Math.sin(r * cols + c) * 30}%`,
                display: 'block',
              }}
            />
          </td>
        ))}
      </tr>
    ))}
  </>
);

export default SkeletonTable;
