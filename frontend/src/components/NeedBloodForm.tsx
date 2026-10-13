import { useState } from 'react';
import type { PatientBloodRequestData } from '../types';

interface NeedBloodFormProps {
  onSuccess: (patientName: string) => void;
  onCancel?: () => void;
}

const DISTRICT_LIST = [
  'Hải Châu',
  'Thanh Khê',
  'Sơn Trà',
  'Ngũ Hành Sơn',
  'Liên Chiểu',
  'Cẩm Lệ',
  'Hòa Vang',
  'Khu vực Quảng Nam',
  'Khu vực khác'
];

export const NeedBloodForm = ({ onSuccess, onCancel }: NeedBloodFormProps) => {
  const [formData, setFormData] = useState<PatientBloodRequestData>({
    patientName: '',
    birthYear: '',
    requestPlatelets: false,
    bloodType: '',
    unitsNeeded: '',
    patientCondition: '',
    hospitalName: '',
    hospitalDistrict: '',
    additionalNotes: '',
    contactName: '',
    contactPhone: '',
    relationship: ''
  });

  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setTimeout(() => {
      setIsSubmitting(false);
      onSuccess(formData.patientName || 'Bệnh nhân');
    }, 600);
  };

  return (
    <div className="custom-form-wrapper">
      <div className="form-header-center">
        <h2 className="form-main-heading">PHIẾU YÊU CẦU MÁU</h2>
        <h3 className="form-sub-heading">DÀNH CHO NGƯỜI NHÀ BỆNH NHÂN</h3>
        <p className="form-desc">
          Vui lòng cung cấp chính xác thông tin để chúng tôi có thể hỗ trợ nhanh nhất.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="custom-form-body">
        {/* Section 1: Thông tin bệnh nhân */}
        <fieldset className="form-card-fieldset">
          <legend className="form-card-legend">Thông tin bệnh nhân</legend>

          <div className="form-row-2col">
            <div className="form-field-group">
              <label className="field-label">
                Họ và tên bệnh nhân <span className="field-req">*</span>
              </label>
              <input
                type="text"
                required
                className="field-input"
                value={formData.patientName}
                onChange={e => setFormData({ ...formData, patientName: e.target.value })}
              />
            </div>

            <div className="form-field-group">
              <label className="field-label">
                Năm sinh <span className="field-req">*</span>
              </label>
              <input
                type="text"
                required
                placeholder="VD: 1985"
                className="field-input"
                value={formData.birthYear}
                onChange={e => setFormData({ ...formData, birthYear: e.target.value })}
              />
            </div>
          </div>

          <div className="form-field-group" style={{ margin: '14px 0' }}>
            <label className="checkbox-item-label inline">
              <input
                type="checkbox"
                checked={formData.requestPlatelets}
                onChange={e => setFormData({ ...formData, requestPlatelets: e.target.checked })}
              />
              <span className="checkbox-title">Yêu cầu hiến tiểu cầu</span>
            </label>
          </div>

          <div className="form-row-2col">
            <div className="form-field-group">
              <label className="field-label">
                Nhóm máu cần <span className="field-req">*</span>
              </label>
              <select
                required
                className="field-select"
                value={formData.bloodType}
                onChange={e => setFormData({ ...formData, bloodType: e.target.value })}
              >
                <option value="">-- Chọn --</option>
                <option value="O">Nhóm máu O</option>
                <option value="A">Nhóm máu A</option>
                <option value="B">Nhóm máu B</option>
                <option value="AB">Nhóm máu AB</option>
                <option value="Chưa rõ">Chưa rõ (Đang chờ xét nghiệm)</option>
              </select>
            </div>

            <div className="form-field-group">
              <label className="field-label">
                Số lượng cần <span className="field-req">*</span>
              </label>
              <input
                type="text"
                required
                placeholder="VD: 2 đơn vị hoặc 4"
                className="field-input"
                value={formData.unitsNeeded}
                onChange={e => setFormData({ ...formData, unitsNeeded: e.target.value })}
              />
            </div>
          </div>

          <div className="form-field-group" style={{ marginTop: '16px' }}>
            <label className="field-label">
              Tình trạng bệnh nhân <span className="field-req">*</span>
            </label>
            <textarea
              required
              rows={2}
              placeholder="VD: Tai nạn giao thông, mất máu nhiều, cần gấp trong đêm..."
              className="field-textarea"
              value={formData.patientCondition}
              onChange={e => setFormData({ ...formData, patientCondition: e.target.value })}
            ></textarea>
          </div>

          <div className="form-row-2col" style={{ marginTop: '16px' }}>
            <div className="form-field-group">
              <label className="field-label">
                Tên bệnh viện <span className="field-req">*</span>
              </label>
              <input
                type="text"
                required
                placeholder="VD: Bệnh viện Đà Nẵng"
                className="field-input"
                value={formData.hospitalName}
                onChange={e => setFormData({ ...formData, hospitalName: e.target.value })}
              />
            </div>

            <div className="form-field-group">
              <label className="field-label">
                Quận/Huyện của bệnh viện <span className="field-req">*</span>
              </label>
              <select
                required
                className="field-select"
                value={formData.hospitalDistrict}
                onChange={e => setFormData({ ...formData, hospitalDistrict: e.target.value })}
              >
                <option value="">-- Chọn khu vực --</option>
                {DISTRICT_LIST.map(d => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-field-group" style={{ marginTop: '16px' }}>
            <label className="field-label">Ghi chú thêm</label>
            <textarea
              rows={2}
              placeholder="VD: Bệnh nhân có tiền sử bệnh nền,..."
              className="field-textarea"
              value={formData.additionalNotes}
              onChange={e => setFormData({ ...formData, additionalNotes: e.target.value })}
            ></textarea>
          </div>
        </fieldset>

        {/* Section 2: Thông tin người liên hệ */}
        <fieldset className="form-card-fieldset">
          <legend className="form-card-legend">Thông tin người liên hệ</legend>

          <div className="form-field-group">
            <label className="field-label">
              Họ tên người liên hệ <span className="field-req">*</span>
            </label>
            <input
              type="text"
              required
              placeholder="VD: Nguyễn Văn An"
              className="field-input"
              value={formData.contactName}
              onChange={e => setFormData({ ...formData, contactName: e.target.value })}
            />
          </div>

          <div className="form-row-2col" style={{ marginTop: '16px' }}>
            <div className="form-field-group">
              <label className="field-label">
                Số điện thoại <span className="field-req">*</span>
              </label>
              <input
                type="tel"
                required
                placeholder="VD: 0905123456"
                className="field-input"
                value={formData.contactPhone}
                onChange={e => setFormData({ ...formData, contactPhone: e.target.value })}
              />
            </div>

            <div className="form-field-group">
              <label className="field-label">
                Mối quan hệ với bệnh nhân <span className="field-req">*</span>
              </label>
              <input
                type="text"
                required
                placeholder="VD: Con trai, Vợ, Chị gái..."
                className="field-input"
                value={formData.relationship}
                onChange={e => setFormData({ ...formData, relationship: e.target.value })}
              />
            </div>
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
            {isSubmitting ? 'Đang gửi thông tin...' : 'Gửi Yêu Cầu'}
          </button>
        </div>
      </form>
    </div>
  );
};
