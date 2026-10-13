import { useState } from 'react';
import { Menu, X } from 'lucide-react';

interface NavbarProps {
  onOpenVolunteer: () => void;
  onOpenInfo: (type: 'about' | 'process' | 'privacy') => void;
  onScrollToNews: () => void;
}

export const Navbar = ({
  onOpenVolunteer,
  onOpenInfo,
  onScrollToNews,
}: NavbarProps) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const handleNavClick = (action: () => void) => {
    action();
    setMobileMenuOpen(false);
  };

  return (
    <header className="navbar-header" id="navbar">
      <div className="navbar-container">
        {/* Brand logo & title */}
        <a href="#navbar" className="brand-link" title="Ngân Hàng Máu Sống Việt Nam">
          <img
            src="/assets/png/logo-mark-red.png"
            alt="Logo Ngân Hàng Máu Sống Việt Nam"
            className="brand-logo-img"
          />
          <div className="brand-text-group">
            <span className="brand-title">NGÂN HÀNG MÁU SỐNG VIỆT NAM</span>
            <span className="brand-tagline">Trọn tình người Việt</span>
          </div>
        </a>

        {/* Desktop Navigation Links */}
        <nav className="nav-menu" aria-label="Menu chính">
          <button
            type="button"
            className="nav-link-item"
            onClick={() => handleNavClick(() => onOpenInfo('about'))}
          >
            Về chúng tôi
          </button>
          <button
            type="button"
            className="nav-link-item"
            onClick={() => handleNavClick(() => onOpenInfo('process'))}
          >
            Quy trình tham gia
          </button>
          <button
            type="button"
            className="nav-link-item"
            onClick={() => handleNavClick(onScrollToNews)}
          >
            Tin tức & sự kiện
          </button>
          <button
            type="button"
            className="nav-link-item"
            onClick={() => handleNavClick(() => onOpenInfo('privacy'))}
          >
            Chính sách bảo mật
          </button>

          {/* CTA Button */}
          <button
            type="button"
            className="nav-cta-btn"
            onClick={() => handleNavClick(onOpenVolunteer)}
          >
            Đăng ký ngay
          </button>
        </nav>

        {/* Mobile Hamburger Button */}
        <button
          type="button"
          className="mobile-toggle-btn"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          aria-label="Mở menu"
        >
          {mobileMenuOpen ? <X size={26} /> : <Menu size={26} />}
        </button>
      </div>

      {/* Mobile Drawer Menu */}
      {mobileMenuOpen && (
        <div className="mobile-nav-drawer">
          <button
            type="button"
            className="nav-link-item"
            onClick={() => handleNavClick(() => onOpenInfo('about'))}
          >
            Về chúng tôi
          </button>
          <button
            type="button"
            className="nav-link-item"
            onClick={() => handleNavClick(() => onOpenInfo('process'))}
          >
            Quy trình tham gia
          </button>
          <button
            type="button"
            className="nav-link-item"
            onClick={() => handleNavClick(onScrollToNews)}
          >
            Tin tức & sự kiện
          </button>
          <button
            type="button"
            className="nav-link-item"
            onClick={() => handleNavClick(() => onOpenInfo('privacy'))}
          >
            Chính sách bảo mật
          </button>
          <button
            type="button"
            className="nav-cta-btn"
            onClick={() => handleNavClick(onOpenVolunteer)}
            style={{ width: '100%', marginTop: '8px' }}
          >
            Đăng ký ngay
          </button>
        </div>
      )}
    </header>
  );
};
