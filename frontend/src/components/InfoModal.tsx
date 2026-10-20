import { X, ShieldCheck, HelpCircle, Activity } from 'lucide-react';

interface InfoModalProps {
  type: 'about' | 'process' | 'privacy' | null;
  onClose: () => void;
}

export const InfoModal = ({ type, onClose }: InfoModalProps) => {
  if (!type) return null;

  const contentMap = {
    about: {
      title: 'Về Chúng Tôi - Giọt Hồng',
      icon: <Activity size={22} />,
      body: (
        <div>
          <p style={{ marginBottom: '14px', lineHeight: 1.6 }}>
            <strong>Giọt Hồng</strong> là dự án vì cộng đồng, được thành lập với mục tiêu xây dựng một mạng lưới dữ liệu người hiến máu tình nguyện sẵn sàng hỗ trợ khẩn cấp trên mọi miền đất nước.
          </p>
          <p style={{ marginBottom: '14px', lineHeight: 1.6 }}>
            Với thông điệp <em>"Trọn tình người Việt"</em>, chúng tôi cam kết kết nối trực tiếp, kịp thời giữa người bệnh cần máu và người tình nguyện hiến máu, giảm thiểu tối đa thời gian chờ đợi trong các ca cấp cứu sinh tử.
          </p>
          <h4 style={{ fontSize: '15px', color: '#0f172a', margin: '14px 0 8px' }}>Mục tiêu cốt lõi:</h4>
          <ul style={{ paddingLeft: '20px', lineHeight: 1.6, color: '#334155' }}>
            <li>Xây dựng cơ sở dữ liệu hiến máu an toàn, bảo mật.</li>
            <li>Hỗ trợ cung ứng máu hiếm (O-, Rh-) tức thì khi bệnh viện thiếu hụt.</li>
            <li>Tuyên truyền, lan tỏa văn hóa hiến máu nhân đạo rộng rãi tới thế hệ trẻ.</li>
          </ul>
        </div>
      )
    },
    process: {
      title: 'Quy Trình Tham Gia Hiến Máu Tình Nguyện',
      icon: <HelpCircle size={22} />,
      body: (
        <div>
          <p style={{ marginBottom: '14px', lineHeight: 1.6 }}>
            Để đảm bảo an toàn tuyệt đối cho người hiến máu và người nhận máu, quy trình tham gia được thực hiện theo 4 bước chuẩn y khoa:
          </p>
          <ol style={{ paddingLeft: '20px', lineHeight: 1.7, color: '#334155' }}>
            <li style={{ marginBottom: '10px' }}>
              <strong>Đăng ký & Điền phiếu thông tin:</strong> Khai báo thông tin cá nhân và tiền sử sức khỏe trực tuyến hoặc tại điểm tiếp nhận.
            </li>
            <li style={{ marginBottom: '10px' }}>
              <strong>Khám sức khỏe sàng lọc:</strong> Đo huyết áp, khám lâm sàng và xét nghiệm nhanh nhóm máu, nồng độ huyết sắc tố (Hb).
            </li>
            <li style={{ marginBottom: '10px' }}>
              <strong>Tiến hành hiến máu:</strong> Quá trình lấy máu diễn ra từ 5 - 10 phút trong điều kiện vô trùng tiêu chuẩn (thể tích 250ml - 450ml).
            </li>
            <li>
              <strong>Nghỉ ngơi & Nhận giấy chứng nhận:</strong> Nghỉ ngơi tại chỗ 15 - 20 phút, nhận suất ăn nhẹ bổ dưỡng và Giấy chứng nhận hiến máu tình nguyện.
            </li>
          </ol>
        </div>
      )
    },
    privacy: {
      title: 'Chính Sách Bảo Mật Thông Tin',
      icon: <ShieldCheck size={22} />,
      body: (
        <div>
          <p style={{ marginBottom: '14px', lineHeight: 1.6 }}>
            Giọt Hồng coi trọng sự riêng tư và bảo mật thông tin cá nhân của các tình nguyện viên và người cần máu.
          </p>
          <h4 style={{ fontSize: '15px', color: '#0f172a', margin: '14px 0 8px' }}>Cam kết của chúng tôi:</h4>
          <ul style={{ paddingLeft: '20px', lineHeight: 1.6, color: '#334155' }}>
            <li style={{ marginBottom: '8px' }}>
              Toàn bộ dữ liệu nhóm máu, số điện thoại, địa chỉ được mã hóa an toàn theo tiêu chuẩn bảo mật dữ liệu y tế.
            </li>
            <li style={{ marginBottom: '8px' }}>
              Chỉ liên hệ với tình nguyện viên khi có ca cấp cứu phù hợp với nhóm máu hoặc có sự đồng thuận từ trước.
            </li>
            <li>
              Tuyệt đối không chia sẻ hoặc thương mại hóa thông tin người dùng cho bất kỳ bên thứ ba nào vì mục đích thương mại.
            </li>
          </ul>
        </div>
      )
    }
  }[type];

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '600px' }}>
        <div className="modal-header">
          <div className="modal-title-row">
            <div className="modal-badge-icon">
              {contentMap.icon}
            </div>
            <div>
              <h3 className="modal-title">{contentMap.title}</h3>
            </div>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Đóng">
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          {contentMap.body}
        </div>

        <div className="modal-footer">
          <button type="button" className="btn-primary" onClick={onClose}>
            Đã hiểu
          </button>
        </div>
      </div>
    </div>
  );
};
