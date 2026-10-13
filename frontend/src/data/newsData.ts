import type { NewsItem } from '../types';

export const NEWS_DATA: NewsItem[] = [
  {
    id: 1,
    date: '22/06/2026',
    title: 'Đà Nẵng ngày càng có nhiều người tham gia hiến máu tình nguyện',
    excerpt: 'Chiều 22/6, tại Đà Nẵng, Ban Chỉ đạo vận động hiến máu tình nguyện thành phố Đà Nẵng tổ chức Lễ tôn vinh, khen thưởng phong trào hiến máu tình nguyện thành phố Đà Nẵng năm 2024.',
    image: '/assets/news/01-hospital-blood-donation.png',
    category: 'su-kien',
    fullContent: 'Chiều 22/6, tại Đà Nẵng, Ban Chỉ đạo vận động hiến máu tình nguyện thành phố Đà Nẵng đã trang trọng tổ chức Lễ tôn vinh, khen thưởng các tập thể, cá nhân và gia đình tiêu biểu trong phong trào hiến máu tình nguyện thành phố Đà Nẵng. Phong trào ngày càng lan tỏa mạnh mẽ, thu hút đông đảo các tầng lớp nhân dân nhiệt tình hưởng ứng tham gia, góp phần quan trọng vào sự nghiệp chăm sóc và bảo vệ sức khỏe nhân dân.'
  },
  {
    id: 2,
    date: '29/12/2025',
    title: 'Công an TP Đà Nẵng tổ chức hiến máu tình nguyện đợt 3, thu hơn 400 đơn vị máu',
    excerpt: "Sáng 29/12, Công an TP Đà Nẵng phối hợp Khoa Huyết học Bệnh viện Đà Nẵng tổ chức Chương trình Hiến máu tình nguyện đợt 3 năm 2023 với chủ đề 'Giọt máu hồng người chiến sĩ'.",
    image: '/assets/news/02-volunteers-in-red.png',
    category: 'su-kien',
    fullContent: "Sáng 29/12, Công an TP Đà Nẵng phối hợp cùng Khoa Huyết học - Truyền máu Bệnh viện Đà Nẵng tổ chức Chương trình Hiến máu tình nguyện đợt 3 với chủ đề 'Giọt máu hồng người chiến sĩ'. Đông đảo cán bộ, chiến sĩ công an từ các đơn vị nghiệp vụ đã hăng hái tham gia, đóng góp hơn 400 đơn vị máu an toàn vào ngân hàng máu dự trữ của thành phố."
  },
  {
    id: 3,
    date: '15/10/2026',
    title: '03 CBCS Phòng Cảnh sát PCCC và CNCH Công an TP Đà Nẵng đến tận bệnh viện hiến máu cứu người',
    excerpt: 'Ngay sau khi nhận được tin báo có bệnh nhân đang điều trị tại Bệnh viện đa khoa khu vực Quảng Nam đang cần gấp 03 đơn vị máu nhóm O, 03 CBCS Phòng Cảnh sát PCCC và CNCH Công an TP Đà Nẵng đã xung phong đến tận bệnh viện để hiến máu cứu bệnh nhân vượt qua cơn nguy kịch...',
    image: '/assets/news/03-donation-close-up.png',
    category: 'khan-cap',
    fullContent: 'Ngay sau khi nhận được tin báo có bệnh nhân nặng đang điều trị tại Bệnh viện đa khoa khu vực Quảng Nam cần truyền gấp 03 đơn vị máu nhóm O để phẫu thuật khẩn cấp, 03 cán bộ chiến sĩ thuộc Phòng Cảnh sát PCCC và CNCH Công an TP Đà Nẵng đã lập tức xung phong đến tận bệnh viện, trực tiếp hiến máu giúp bệnh nhân qua cơn nguy kịch. Nghĩa cử cao đẹp này đã nhận được sự cảm phục sâu sắc từ gia đình bệnh nhân và y bác sĩ.'
  },
  {
    id: 4,
    date: '18/01/2026',
    title: "Hơn 1.000 thanh niên Đà Nẵng hiến máu tình nguyện trong ngày 'Chủ Nhật Đỏ'",
    excerpt: "Sự kiện hiến máu tình nguyện 'Chủ Nhật Đỏ' đã thu hút hơn 2.000 sinh viên và cán bộ giảng viên tham gia, tiếp nhận gần 1.500 đơn vị máu an toàn.",
    image: '/assets/news/04-blood-storage-bags.png',
    category: 'su-kien',
    fullContent: "Chương trình 'Chủ Nhật Đỏ' lần thứ XVI với thông điệp 'Hiến máu cứu người - Sinh mệnh của bạn và tôi' đã diễn ra sôi nổi tại Đà Nẵng. Sự kiện thu hút hơn 2.000 đoàn viên, thanh niên, sinh viên và cán bộ giảng viên các trường đại học tham gia, tiếp nhận gần 1.500 đơn vị máu quý giá phục vụ cấp cứu dịp đầu năm mới."
  },
  {
    id: 5,
    date: '10/09/2026',
    title: 'Bệnh viện Đa khoa Tam Kỳ kêu gọi khẩn cấp nhóm máu A và O cho các ca mổ tim',
    excerpt: 'Do nhu cầu phẫu thuật tim mạch tăng đột biến, lượng máu dự trữ nhóm A và O tại Bệnh viện Đa khoa Quảng Nam (Tam Kỳ) đang ở mức báo động. Rất cần sự chung tay của cộng đồng.',
    image: '/assets/news/05-hands-red-heart.png',
    category: 'khan-cap',
    fullContent: 'Do nhu cầu phẫu thuật tim mạch và điều trị hồi sức cấp cứu tăng cao đột biến, lượng máu dự trữ nhóm A và nhóm O tại Bệnh viện Đa khoa Quảng Nam (Tam Kỳ) đang ở mức báo động đỏ. Ban giám đốc bệnh viện tha thiết kêu gọi các tình nguyện viên, người dân có đủ điều kiện sức khỏe đến tham gia hiến máu để hỗ trợ kịp thời cho các bệnh nhân hiểm nghèo.'
  },
  {
    id: 6,
    date: '12/08/2026',
    title: "Công an Đà Nẵng tổ chức ngày hội 'Giọt hồng người chiến sĩ'",
    excerpt: "Sáng 12/8, Công an thành phố Đà Nẵng tổ chức Ngày hội hiến máu tình nguyện 'Giọt hồng người chiến sĩ' năm 2025. Chương trình đã tiếp nhận khoảng 500 đơn vị máu từ cán bộ, chiến sĩ, đoàn viên thanh niên công an các đơn vị trực thuộc Công an thành phố và công an các xã, phường.",
    image: '/assets/news/06-volunteer-event.png',
    category: 'su-kien',
    fullContent: "Sáng 12/8, Công an thành phố Đà Nẵng tổ chức Ngày hội hiến máu tình nguyện 'Giọt hồng người chiến sĩ' năm 2025. Chương trình tiếp nhận khoảng 500 đơn vị máu từ cán bộ, chiến sĩ, đoàn viên thanh niên công an các đơn vị trực thuộc Công an thành phố và công an các xã, phường, thể hiện tinh thần xung kích vì cộng đồng."
  },
  {
    id: 7,
    date: '05/08/2026',
    title: 'Hiến máu an toàn và sức khỏe cộng đồng',
    excerpt: 'Tuân thủ quy trình, đảm bảo an toàn cho người hiến máu và người nhận máu. Những quy định và hướng dẫn y tế cần ghi nhớ trước khi tham gia hiến máu.',
    image: '/assets/news/07-safe-donation.png',
    category: 'chia-se',
    fullContent: 'Các chuyên gia y tế khuyến cáo người tham gia hiến máu cần tuân thủ đầy đủ các nguyên tắc sức khỏe: ngủ đủ giấc đêm trước ngày hiến máu, ăn nhẹ trước khi hiến (không ăn đồ nhiều dầu mỡ), uống nhiều nước, và tránh sử dụng chất kích thích. Quy trình lấy máu hoàn toàn khép kín, sử dụng dụng cụ vô trùng một lần, tuyệt đối an toàn cho sức khỏe người hiến.'
  }
];
