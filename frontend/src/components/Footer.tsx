interface FooterProps {
  onOpenInfo: (type: 'about' | 'process' | 'privacy') => void;
}

export const Footer = ({ onOpenInfo }: FooterProps) => {
  return (
    <footer className="footer-section" id="footer" aria-label="Chân trang Ngân Hàng Máu Sống">
      <div className="footer-inner-container">
        {/* Top 3 columns */}
        <div className="footer-columns-row">
          {/* Column 1: Brand Info */}
          <div className="footer-col-brand">
            <div className="footer-logo-wrapper">
              <img
                src="/assets/png/logo-mark-white.png"
                alt="Logo Ngân Hàng Máu Sống Trắng"
                className="footer-logo-img"
              />
            </div>
            <h4 className="footer-brand-title">NGÂN HÀNG MÁU SỐNG VIỆT NAM</h4>
            <p className="footer-brand-desc">
              Dự án cộng đồng kết nối người tình nguyện hiến máu vì một xã hội khỏe mạnh hơn.
            </p>
          </div>

          {/* Column 2: Quick Links */}
          <div className="footer-col-links">
            <h4 className="footer-col-title">Liên kết nhanh</h4>
            <ul className="footer-links-list">
              <li>
                <button
                  type="button"
                  className="footer-link-item"
                  onClick={() => onOpenInfo('about')}
                >
                  <span className="footer-link-chevron" aria-hidden="true">&gt;</span>
                  <span>Về chúng tôi</span>
                </button>
              </li>
              <li>
                <button
                  type="button"
                  className="footer-link-item"
                  onClick={() => onOpenInfo('process')}
                >
                  <span className="footer-link-chevron" aria-hidden="true">&gt;</span>
                  <span>Quy trình tham gia</span>
                </button>
              </li>
              <li>
                <button
                  type="button"
                  className="footer-link-item"
                  onClick={() => onOpenInfo('privacy')}
                >
                  <span className="footer-link-chevron" aria-hidden="true">&gt;</span>
                  <span>Chính sách bảo mật</span>
                </button>
              </li>
            </ul>
          </div>

          {/* Column 3: Social Connect */}
          <div className="footer-col-social">
            <h4 className="footer-col-title">Kết nối</h4>
            <div className="footer-social-row">
              <a
                href="https://facebook.com"
                target="_blank"
                rel="noopener noreferrer"
                className="social-circle-btn facebook"
                title="Theo dõi chúng tôi trên Facebook"
                aria-label="Facebook"
              >
                <span>f</span>
              </a>
              <a
                href="https://zalo.me"
                target="_blank"
                rel="noopener noreferrer"
                className="social-circle-btn zalo"
                title="Liên hệ qua Zalo"
                aria-label="Zalo"
              >
                <span>Zalo</span>
              </a>
            </div>
          </div>
        </div>

        {/* Divider line */}
        <hr className="footer-divider-line" />

        {/* Bottom copyright & message */}
        <div className="footer-bottom-group">
          <p className="footer-motto">
            Chung tay lan tỏa nguồn máu nhân ái, vì một cộng đồng khỏe mạnh hơn.
          </p>
          <p className="footer-copyright">
            © 2026 Bản quyền thuộc về Ngân hàng Máu Sống Việt Nam.
          </p>
        </div>
      </div>
    </footer>
  );
};
