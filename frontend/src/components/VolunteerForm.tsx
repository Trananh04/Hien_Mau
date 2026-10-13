import { useState } from 'react';
import type { VolunteerRegistrationData } from '../types';

interface VolunteerFormProps {
  onSuccess: (name: string) => void;
  onCancel?: () => void;
}

const DONATION_AREAS = [
  'Đà Nẵng cũ (Hải Châu, Thanh Khê, Sơn Trà, Ngũ Hành Sơn, Liên Chiểu, Cẩm Lệ, Hòa Vang)',
  'Bắc Quảng Nam (Duy Xuyên, Đại Lộc, Điện Bàn, Hội An)',
  'Miền núi Bắc Quảng Nam (Tây Giang, Đông Giang)',
  'Đông Quảng Nam (Quế Sơn, Thăng Bình, Hiệp Đức)',
  'Tây Quảng Nam (Phước Sơn, Nam Giang)',
  'Nam Quảng Nam (Tam Kỳ, Tiên Phước, Núi Thành, Phú Ninh)',
  'Miền núi Nam Quảng Nam (Bắc Trà My, Nam Trà My)'
];

export const VolunteerForm = ({ onSuccess, onCancel }: VolunteerFormProps) => {
  const [formData, setFormData] = useState<VolunteerRegistrationData>({
    fullName: '',
    birthYear: '',
    address: '',
    gender: 'Nam',
    phone: '',
    zalo: '',
    bloodType: '',
    rhFactor: 'Rh+',
    donationStatus: 'Chưa từng hiến',
    canDonatePlatelets: 'Chưa rõ',
    selectedAreas: []
  });

  const [isAllSelected, setIsAllSelected] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleToggleAllAreas = (checked: boolean) => {
    setIsAllSelected(checked);
    if (checked) {
      setFormData(prev => ({ ...prev, selectedAreas: [...DONATION_AREAS] }));
    } else {
      setFormData(prev => ({ ...prev, selectedAreas: [] }));
    }
  };

  const handleToggleArea = (area: string) => {
    setFormData(prev => {
      const exists = prev.selectedAreas.includes(area);
      const updated = exists
        ? prev.selectedAreas.filter(a => a !== area)
        : [...prev.selectedAreas, area];
      
      setIsAllSelected(updated.length === DONATION_AREAS.length);
      return { ...prev, selectedAreas: updated };
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setTimeout(() => {
      setIsSubmitting(false);
      onSuccess(formData.fullName || 'Tình nguyện viên');
    }, 600);
  };

  return (
    <div className="custom-form-wrapper">
      <div className="form-header-center">
        <h2 className="form-main-heading">PHIẾU ĐĂNG KÝ</h2>
        <h3 className="form-sub-heading">TRỞ THÀNH TÌNH NGUYỆN VIÊN HIẾN MÁU</h3>
        <p className="form-desc">
          Hãy điền đầy đủ thông tin dưới đây để tham gia cùng chúng tôi trong hành trình cứu người.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="custom-form-body">
        {/* Section 1: Thông tin cá nhân */}
        <fieldset className="form-card-fieldset">
          <legend className="form-card-legend">Thông tin cá nhân</legend>

          <div className="form-row-2col">
            <div className="form-field-group">
              <label className="field-label">
                Họ và tên <span className="field-req">*</span>
              </label>
              <input
                type="text"
                required
                className="field-input"
                value={formData.fullName}
                onChange={e => setFormData({ ...formData, fullName: e.target.value })}
              />
            </div>

            <div className="form-field-group">
              <label className="field-label">
                Năm sinh <span className="field-req">*</span>
              </label>
              <input
                type="text"
                required
                placeholder="VD: 1995"
                className="field-input"
                value={formData.birthYear}
                onChange={e => setFormData({ ...formData, birthYear: e.target.value })}
              />
            </div>
          </div>

          <div className="form-field-group" style={{ marginTop: '16px' }}>
            <label className="field-label">
              Địa chỉ thường trú <span className="field-req">*</span>
            </label>
            <input
              type="text"
              required
              placeholder="VD: 561 Núi Thành, Hòa Cường, TP. Đà Nẵng"
              className="field-input"
              value={formData.address}
              onChange={e => setFormData({ ...formData, address: e.target.value })}
            />
          </div>

          <div className="form-field-group" style={{ marginTop: '16px' }}>
            <label className="field-label">
              Giới tính <span className="field-req">*</span>
            </label>
            <div className="radio-group-row">
              <label className="radio-label">
                <input
                  type="radio"
                  name="gender"
                  value="Nam"
                  checked={formData.gender === 'Nam'}
                  onChange={() => setFormData({ ...formData, gender: 'Nam' })}
                />
                <span>Nam</span>
              </label>
              <label className="radio-label">
                <input
                  type="radio"
                  name="gender"
                  value="Nữ"
                  checked={formData.gender === 'Nữ'}
                  onChange={() => setFormData({ ...formData, gender: 'Nữ' })}
                />
                <span>Nữ</span>
              </label>
              <label className="radio-label">
                <input
                  type="radio"
                  name="gender"
                  value="Khác"
                  checked={formData.gender === 'Khác'}
                  onChange={() => setFormData({ ...formData, gender: 'Khác' })}
                />
                <span>Khác</span>
              </label>
            </div>
          </div>
        </fieldset>

        {/* Section 2: Thông tin liên hệ */}
        <fieldset className="form-card-fieldset">
          <legend className="form-card-legend">Thông tin liên hệ</legend>

          <div className="form-row-2col">
            <div className="form-field-group">
              <label className="field-label">
                Số điện thoại <span className="field-req">*</span>
              </label>
              <input
                type="tel"
                required
                className="field-input"
                value={formData.phone}
                onChange={e => setFormData({ ...formData, phone: e.target.value })}
              />
            </div>

            <div className="form-field-group">
              <label className="field-label">Zalo (nếu khác SĐT)</label>
              <input
                type="text"
                className="field-input"
                value={formData.zalo}
                onChange={e => setFormData({ ...formData, zalo: e.target.value })}
              />
            </div>
          </div>
        </fieldset>

        {/* Section 3: Thông tin y tế */}
        <fieldset className="form-card-fieldset">
          <legend className="form-card-legend">Thông tin y tế</legend>

          <div className="form-row-3col">
            <div className="form-field-group">
              <label className="field-label">
                Nhóm máu <span className="field-req">*</span>
              </label>
              <select
                required
                className="field-select"
                value={formData.bloodType}
                onChange={e => setFormData({ ...formData, bloodType: e.target.value })}
              >
                <option value="">-- Chọn nhóm máu --</option>
                <option value="O">Nhóm máu O</option>
                <option value="A">Nhóm máu A</option>
                <option value="B">Nhóm máu B</option>
                <option value="AB">Nhóm máu AB</option>
                <option value="Chưa rõ">Chưa rõ nhóm máu</option>
              </select>
            </div>

            <div className="form-field-group">
              <label className="field-label">
                Yếu tố Rh <span className="field-req">*</span>
              </label>
              <div className="radio-group-row compact">
                <label className="radio-label">
                  <input
                    type="radio"
                    name="rhFactor"
                    value="Rh+"
                    checked={formData.rhFactor === 'Rh+'}
                    onChange={() => setFormData({ ...formData, rhFactor: 'Rh+' })}
                  />
                  <span>Rh+</span>
                </label>
                <label className="radio-label">
                  <input
                    type="radio"
                    name="rhFactor"
                    value="Rh-"
                    checked={formData.rhFactor === 'Rh-'}
                    onChange={() => setFormData({ ...formData, rhFactor: 'Rh-' })}
                  />
                  <span>Rh-</span>
                </label>
                <label className="radio-label">
                  <input
                    type="radio"
                    name="rhFactor"
                    value="Chưa rõ"
                    checked={formData.rhFactor === 'Chưa rõ'}
                    onChange={() => setFormData({ ...formData, rhFactor: 'Chưa rõ' })}
                  />
                  <span>Chưa rõ</span>
                </label>
              </div>
            </div>

            <div className="form-field-group">
              <label className="field-label">
                Tình trạng hiến máu <span className="field-req">*</span>
              </label>
              <select
                className="field-select"
                value={formData.donationStatus}
                onChange={e => setFormData({ ...formData, donationStatus: e.target.value })}
              >
                <option value="Chưa từng hiến">Chưa từng hiến</option>
                <option value="Đã hiến 1 - 2 lần">Đã hiến 1 - 2 lần</option>
                <option value="Đã hiến 3 - 5 lần">Đã hiến 3 - 5 lần</option>
                <option value="Đã hiến trên 5 lần">Đã hiến trên 5 lần</option>
              </select>
            </div>
          </div>

          <div className="form-field-group" style={{ marginTop: '18px' }}>
            <label className="field-label">
              Khả năng hiến tiểu cầu <span className="field-req">*</span>
            </label>
            <div className="radio-group-row">
              <label className="radio-label">
                <input
                  type="radio"
                  name="canDonatePlatelets"
                  value="Có"
                  checked={formData.canDonatePlatelets === 'Có'}
                  onChange={() => setFormData({ ...formData, canDonatePlatelets: 'Có' })}
                />
                <span>Có (Tĩnh mạch tốt)</span>
              </label>
              <label className="radio-label">
                <input
                  type="radio"
                  name="canDonatePlatelets"
                  value="Không"
                  checked={formData.canDonatePlatelets === 'Không'}
                  onChange={() => setFormData({ ...formData, canDonatePlatelets: 'Không' })}
                />
                <span>Không</span>
              </label>
              <label className="radio-label">
                <input
                  type="radio"
                  name="canDonatePlatelets"
                  value="Chưa rõ"
                  checked={formData.canDonatePlatelets === 'Chưa rõ'}
                  onChange={() => setFormData({ ...formData, canDonatePlatelets: 'Chưa rõ' })}
                />
                <span>Chưa rõ / Cần tư vấn</span>
              </label>
            </div>
          </div>
        </fieldset>

        {/* Section 4: Khu vực có thể hiến máu */}
        <fieldset className="form-card-fieldset">
          <legend className="form-card-legend">Khu vực có thể hiến máu</legend>

          <p className="area-instruction-note">
            Chọn một hoặc nhiều khu vực bạn sẵn sàng và có thể di chuyển đến để hiến máu khi có trường hợp khẩn cấp. Nếu người cần máu nằm ngoài khu vực bạn đăng ký, bạn sẽ không nhận được thông báo!!!
          </p>

          <div className="checkboxes-list-group">
            <label className="checkbox-item-label highlight-all">
              <input
                type="checkbox"
                checked={isAllSelected}
                onChange={e => handleToggleAllAreas(e.target.checked)}
              />
              <span className="checkbox-title">Tất cả (toàn thành phố Đà Nẵng mới)</span>
            </label>

            {DONATION_AREAS.map(area => (
              <label key={area} className="checkbox-item-label">
                <input
                  type="checkbox"
                  checked={formData.selectedAreas.includes(area)}
                  onChange={() => handleToggleArea(area)}
                />
                <span className="checkbox-title">{area}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {/* Submit Button */}
        <div className="form-actions-row">
          {onCancel && (
            <button type="button" className="btn-form-cancel" onClick={onCancel}>
              Hủy bỏ
            </button>
          )}
          <button type="submit" className="btn-form-submit-red" disabled={isSubmitting}>
            {isSubmitting ? 'Đang gửi thông tin...' : 'Đăng Ký Tham Gia'}
          </button>
        </div>
      </form>
    </div>
  );
};
