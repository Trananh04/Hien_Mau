import { CrossButton } from './CrossButton';
import { HeartButton } from './HeartButton';

interface HeroProps {
  onOpenVolunteer: () => void;
  onOpenNeedBlood: () => void;
}

export const Hero = ({
  onOpenVolunteer,
  onOpenNeedBlood,
}: HeroProps) => {
  return (
    <section className="hero-section" aria-label="Giới thiệu Ngân Hàng Máu Sống">
      {/* Dong Son drum watermark top-right */}
      <img
        src="/assets/svg/dong-son-drum.svg"
        alt=""
        aria-hidden="true"
        className="hero-drum-bg"
      />

      {/* Floating 3D Heart Blood Drop vector at right */}
      <img
        src="/assets/png/heart-blood-drop-vector.png"
        alt="Trái tim và giọt máu nhân ái"
        className="hero-heart-vector"
      />

      {/* Hero flowing ribbon waves at bottom */}
      <img
        src="/assets/png/hero-waves.png"
        alt=""
        aria-hidden="true"
        className="hero-waves-ribbon"
      />

      {/* Center Main Content */}
      <div className="hero-content-wrapper">
        <h1 className="hero-main-title">NGÂN HÀNG MÁU SỐNG VIỆT NAM</h1>

        <div className="hero-greeting">Xin chào</div>

        <p className="hero-description">
          Hãy đăng ký tham gia cùng chúng tôi để tạo ra nguồn máu vô tận, sẵn sàng
          giúp đỡ cộng đồng và lan tỏa những giá trị nhân văn cao đẹp.
        </p>

        {/* Action Buttons with Interactive Hover Flip and Moving Decorations */}
        <div className="hero-action-buttons">
          {/* Nút 1: Trái Tim Yêu Thương (Mặc định: Đăng ký Tình nguyện viên -> Hover: Hiến máu cứu người) */}
          <HeartButton
            defaultText="Đăng ký Tình nguyện viên"
            hoverText="Hiến máu cứu người"
            onClick={onOpenVolunteer}
            title="Đăng ký làm tình nguyện viên hiến máu"
          />

          {/* Nút 2: Thập Đỏ Y Tế (Mặc định: Tôi cần xin máu -> Hover: Chúng tôi sẽ giúp đỡ) */}
          <CrossButton
            defaultText="Tôi cần xin máu"
            hoverText="Chúng tôi sẽ giúp đỡ"
            onClick={onOpenNeedBlood}
            title="Gửi yêu cầu cần máu khẩn cấp"
          />
        </div>
      </div>
    </section>
  );
};
