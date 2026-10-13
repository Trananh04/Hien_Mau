import { X, Calendar, Share2 } from 'lucide-react';
import type { NewsItem } from '../types';

interface NewsDetailModalProps {
  news: NewsItem | null;
  onClose: () => void;
  onShare: () => void;
}

export const NewsDetailModal = ({
  news,
  onClose,
  onShare,
}: NewsDetailModalProps) => {
  if (!news) return null;

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '680px' }}>
        <div className="modal-header">
          <div className="modal-title-row">
            <span style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              color: '#2563eb',
              fontSize: '13px',
              fontWeight: 600
            }}>
              <Calendar size={16} />
              {news.date}
            </span>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Đóng">
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          <div style={{
            width: '100%',
            height: '240px',
            borderRadius: '10px',
            overflow: 'hidden',
            marginBottom: '18px'
          }}>
            <img
              src={news.image}
              alt={news.title}
              style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />
          </div>

          <h2 style={{
            fontSize: '20px',
            fontWeight: 800,
            color: '#0f172a',
            lineHeight: 1.35,
            marginBottom: '12px'
          }}>
            {news.title}
          </h2>

          <p style={{
            fontSize: '15px',
            fontWeight: 500,
            color: '#1e3a8a',
            marginBottom: '16px',
            lineHeight: 1.6,
            fontStyle: 'italic',
            borderLeft: '3px solid #dc2626',
            paddingLeft: '12px'
          }}>
            {news.excerpt}
          </p>

          <div style={{
            fontSize: '14.5px',
            color: '#334155',
            lineHeight: 1.75
          }}>
            <p>{news.fullContent}</p>
          </div>
        </div>

        <div className="modal-footer" style={{ justifyContent: 'space-between' }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={onShare}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}
          >
            <Share2 size={16} />
            <span>Chia sẻ tin tức</span>
          </button>

          <button type="button" className="btn-primary" onClick={onClose}>
            Đóng bài viết
          </button>
        </div>
      </div>
    </div>
  );
};
