import { X } from 'lucide-react';
import { NeedBloodForm } from './NeedBloodForm';

interface NeedBloodModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmitSuccess: (patientName: string) => void;
}

export const NeedBloodModal = ({
  isOpen,
  onClose,
  onSubmitSuccess,
}: NeedBloodModalProps) => {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div
        className="modal-dialog form-page-modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '780px', maxHeight: '92vh', overflowY: 'auto' }}
      >
        <div style={{ position: 'sticky', top: 0, zIndex: 10, display: 'flex', justifyContent: 'flex-end', padding: '12px 16px 0', background: '#ffffff' }}>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Đóng"
            style={{ padding: '6px', borderRadius: '50%', background: '#f1f5f9' }}
          >
            <X size={20} />
          </button>
        </div>

        <div style={{ padding: '0 28px 28px' }}>
          <NeedBloodForm
            onSuccess={(name) => {
              onSubmitSuccess(name);
              onClose();
            }}
            onCancel={onClose}
          />
        </div>
      </div>
    </div>
  );
};
