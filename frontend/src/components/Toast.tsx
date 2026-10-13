import { CheckCircle2, X } from 'lucide-react';

interface ToastProps {
  message: string | null;
  onClose: () => void;
}

export const Toast = ({ message, onClose }: ToastProps) => {
  if (!message) return null;

  return (
    <div className="toast-container">
      <div className="toast-item success" role="alert">
        <CheckCircle2 size={22} color="#10b981" />
        <span style={{ fontSize: '14px', fontWeight: 500, color: '#0f172a', flex: 1 }}>{message}</span>
        <button
          type="button"
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: '2px' }}
          aria-label="Đóng thông báo"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  );
};
