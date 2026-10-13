import { useState } from 'react';
import './App.css';
import { Navbar } from './components/Navbar';
import { Hero } from './components/Hero';
import { NewsSection } from './components/NewsSection';
import { Footer } from './components/Footer';
import { VolunteerModal } from './components/VolunteerModal';
import { NeedBloodModal } from './components/NeedBloodModal';
import { NewsDetailModal } from './components/NewsDetailModal';
import { InfoModal } from './components/InfoModal';
import { Toast } from './components/Toast';
import type { NewsItem } from './types';

export function App() {
  const [isVolunteerOpen, setIsVolunteerOpen] = useState(false);
  const [isNeedBloodOpen, setIsNeedBloodOpen] = useState(false);
  const [selectedNews, setSelectedNews] = useState<NewsItem | null>(null);
  const [infoType, setInfoType] = useState<'about' | 'process' | 'privacy' | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const triggerToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage(null);
    }, 4000);
  };

  const scrollToNews = () => {
    const el = document.getElementById('tin-tuc');
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="app-wrapper">
      {/* Top Navigation */}
      <Navbar
        onOpenVolunteer={() => setIsVolunteerOpen(true)}
        onOpenInfo={(type) => setInfoType(type)}
        onScrollToNews={scrollToNews}
      />

      {/* Main Content Area */}
      <main>
        {/* Hero Section */}
        <Hero
          onOpenVolunteer={() => setIsVolunteerOpen(true)}
          onOpenNeedBlood={() => setIsNeedBloodOpen(true)}
        />

        {/* News & Activity Section */}
        <NewsSection onSelectNews={(item) => setSelectedNews(item)} />
      </main>

      {/* Footer */}
      <Footer onOpenInfo={(type) => setInfoType(type)} />

      {/* Modals & Dialogs */}
      <VolunteerModal
        isOpen={isVolunteerOpen}
        onClose={() => setIsVolunteerOpen(false)}
        onSubmitSuccess={(name) => {
          triggerToast(`Cảm ơn ${name}! Đăng ký hiến máu tình nguyện thành công.`);
        }}
      />

      <NeedBloodModal
        isOpen={isNeedBloodOpen}
        onClose={() => setIsNeedBloodOpen(false)}
        onSubmitSuccess={(patientName) => {
          triggerToast(`Đã tiếp nhận yêu cầu cần máu cho ${patientName}. Chúng tôi đang kết nối điều phối!`);
        }}
      />

      <NewsDetailModal
        news={selectedNews}
        onClose={() => setSelectedNews(null)}
        onShare={() => {
          triggerToast('Đã sao chép liên kết bài viết vào clipboard!');
        }}
      />

      <InfoModal
        type={infoType}
        onClose={() => setInfoType(null)}
      />

      {/* Toast Feedback */}
      <Toast message={toastMessage} onClose={() => setToastMessage(null)} />
    </div>
  );
}

export default App;
