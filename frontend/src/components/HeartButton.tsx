import { useState } from 'react';

interface HeartButtonProps {
  defaultText: string;
  hoverText: string;
  onClick: () => void;
  title?: string;
  ariaLabel?: string;
}

export const HeartButton = ({
  defaultText,
  hoverText,
  onClick,
  title,
  ariaLabel,
}: HeartButtonProps) => {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <button
      type="button"
      className={`btn-heart-theme interactive-flip-btn ${isHovered ? 'hovered' : ''}`}
      onClick={onClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      title={title || defaultText}
      aria-label={ariaLabel || defaultText}
    >
      {/* Dynamic Animated Text Container */}
      <div className="flip-text-container">
        <span className="btn-heart-text flip-text-default">{defaultText}</span>
        <span className="btn-heart-text flip-text-hover">{hoverText}</span>
      </div>
    </button>
  );
};
