import { useState } from 'react';

interface CrossButtonProps {
  defaultText: string;
  hoverText: string;
  onClick: () => void;
  title?: string;
  ariaLabel?: string;
}

export const CrossButton = ({
  defaultText,
  hoverText,
  onClick,
  title,
  ariaLabel,
}: CrossButtonProps) => {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <button
      type="button"
      className={`btn-cross-theme interactive-flip-btn ${isHovered ? 'hovered' : ''}`}
      onClick={onClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      title={title || defaultText}
      aria-label={ariaLabel || defaultText}
    >
      {/* Decorative Red Crosses SVG with animated individual moving elements */}
      <svg
        viewBox="0 0 280 72"
        className="btn-crosses-svg"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <defs>
          <filter id="stamp-glow" x="-10%" y="-10%" width="120%" height="120%">
            <feDropShadow dx="0" dy="0" stdDeviation="0.4" floodColor="#d90429" floodOpacity="0.4" />
          </filter>
        </defs>

        <g fill="#d90429" filter="url(#stamp-glow)">
          {/* Top Row Crosses */}
          <g className="cross-elem ce-1">
            <rect x="25" y="6" width="8" height="22" rx="1.5" />
            <rect x="18" y="13" width="22" height="8" rx="1.5" />
          </g>

          <g className="cross-elem ce-2">
            <rect x="62" y="10" width="4.5" height="13" rx="1" />
            <rect x="58" y="14.2" width="13" height="4.5" rx="1" />
          </g>

          <g className="cross-elem ce-3">
            <rect x="103" y="7" width="5.5" height="16" rx="1" />
            <rect x="98" y="12.2" width="16" height="5.5" rx="1" />
          </g>

          <g className="cross-elem ce-4">
            <rect x="175" y="6" width="4" height="12" rx="0.8" />
            <rect x="171" y="10" width="12" height="4" rx="0.8" />
          </g>

          <g className="cross-elem ce-5">
            <rect x="231" y="6" width="8" height="22" rx="1.5" />
            <rect x="224" y="13" width="22" height="8" rx="1.5" />
          </g>

          <g className="cross-elem ce-6">
            <rect x="261" y="10" width="4.5" height="13.5" rx="1" />
            <rect x="256.5" y="14.5" width="13.5" height="4.5" rx="1" />
          </g>

          {/* Left & Right Edge Middle Crosses */}
          <g className="cross-elem ce-7">
            <rect x="17" y="30" width="5" height="15" rx="1" />
            <rect x="12" y="35" width="15" height="5" rx="1" />
          </g>

          <g className="cross-elem ce-8">
            <rect x="246" y="27" width="4" height="12" rx="0.8" />
            <rect x="242" y="31" width="12" height="4" rx="0.8" />
          </g>

          {/* Bottom Row Crosses */}
          <g className="cross-elem ce-9">
            <rect x="28" y="50" width="4.5" height="13" rx="1" />
            <rect x="24" y="54.2" width="13" height="4.5" rx="1" />
          </g>

          <g className="cross-elem ce-10">
            <rect x="50" y="50" width="4.5" height="13" rx="1" />
            <rect x="46" y="54.2" width="13" height="4.5" rx="1" />
          </g>

          <g className="cross-elem ce-11">
            <rect x="92" y="49" width="6.5" height="18" rx="1.2" />
            <rect x="86" y="54.8" width="18" height="6.5" rx="1.2" />
          </g>

          <g className="cross-elem ce-12">
            <rect x="146" y="57" width="3" height="9" rx="0.6" />
            <rect x="143" y="60" width="9" height="3" rx="0.6" />
          </g>

          <g className="cross-elem ce-13">
            <rect x="219" y="55" width="4" height="12" rx="0.8" />
            <rect x="215" y="59" width="12" height="4" rx="0.8" />
          </g>

          <g className="cross-elem ce-14">
            <rect x="258" y="44" width="8" height="22" rx="1.5" />
            <rect x="251" y="51" width="22" height="8" rx="1.5" />
          </g>
        </g>
      </svg>

      {/* Dynamic Animated Text Container */}
      <div className="flip-text-container">
        <span className="btn-cross-text flip-text-default">{defaultText}</span>
        <span className="btn-cross-text flip-text-hover">{hoverText}</span>
      </div>
    </button>
  );
};
