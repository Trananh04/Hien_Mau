import type { NewsItem } from '../types';
import { NEWS_DATA } from '../data/newsData';

interface NewsSectionProps {
  onSelectNews: (item: NewsItem) => void;
}

export const NewsSection = ({ onSelectNews }: NewsSectionProps) => {
  return (
    <section className="news-section" id="tin-tuc" aria-label="Tin tức hoạt động hiến máu">
      {/* Section Header */}
      <div className="news-section-header">
        <h2 className="news-section-title">TIN TỨC HOẠT ĐỘNG HIẾN MÁU</h2>
        <div className="news-title-underline" aria-hidden="true"></div>
      </div>

      {/* Infinite Auto-Scrolling Marquee Container spanning full width */}
      <div className="news-marquee-container">
        <div className="news-marquee-track">
          {/* We repeat the group 4 times to ensure a perfectly seamless loop on any screen width (even 2560px / 4K) */}
          {[1, 2, 3, 4].map((groupIndex) => (
            <div
              key={`news-group-${groupIndex}`}
              className="news-marquee-group"
              aria-hidden={groupIndex > 1 ? 'true' : undefined}
            >
              {NEWS_DATA.map((item) => (
                <article
                  key={`item-${groupIndex}-${item.id}`}
                  className="news-card"
                  onClick={() => onSelectNews(item)}
                  tabIndex={groupIndex === 1 ? 0 : -1}
                  role="button"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      onSelectNews(item);
                    }
                  }}
                >
                  <div className="news-card-img-wrapper">
                    <img
                      src={item.image}
                      alt={item.title}
                      className="news-card-img"
                      loading="lazy"
                    />
                  </div>

                  <div className="news-card-body">
                    <h3 className="news-card-title">{item.title}</h3>
                    <p className="news-card-excerpt">{item.excerpt}</p>
                  </div>
                </article>
              ))}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};
