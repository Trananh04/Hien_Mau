# 3.2. Thiết kế tích hợp AI

## 3.2.1. Kiến trúc tổng thể và nguyên lý tích hợp AI

Nhằm hỗ trợ bệnh viện điều phối nguồn máu và giúp người dân tiếp cận thông tin hiến máu thuận tiện hơn, hệ thống được tích hợp ba chức năng trí tuệ nhân tạo: gợi ý người hiến máu phù hợp, dự báo nhu cầu sử dụng máu và chatbot tư vấn hiến máu. Do mỗi chức năng giải quyết một dạng bài toán khác nhau, hệ thống không dùng chung một mô hình mà lựa chọn kỹ thuật phù hợp cho từng chức năng.

Chức năng gợi ý người hiến là bài toán xếp hạng, sử dụng mô hình hồi quy logistic và XGBoost để dự đoán khả năng một người nhận lời kêu gọi. Chức năng dự báo là bài toán chuỗi thời gian, sử dụng XGBoost với hàm mục tiêu Poisson để dự báo số đơn vị máu cần dùng mỗi ngày. Chatbot là bài toán hỏi đáp bằng ngôn ngữ tự nhiên, sử dụng mô hình ngôn ngữ lớn Qwen3 kết hợp kỹ thuật Retrieval-Augmented Generation (RAG).

Toàn bộ hệ thống được triển khai bằng Docker, gồm các thành phần: ứng dụng web Django xử lý giao diện và nghiệp vụ; tác vụ định kỳ (scheduler) chạy dự báo mỗi đêm và huấn luyện lại mô hình; cơ sở dữ liệu PostgreSQL; và máy chủ Ollama chạy mô hình ngôn ngữ ngay trên máy chủ của hệ thống. Cách triển khai tại chỗ giúp dữ liệu người dùng không phải gửi ra dịch vụ bên ngoài, đồng thời không phát sinh chi phí sử dụng API.

Việc tích hợp AI tuân theo các nguyên tắc sau. Thứ nhất, AI chỉ đóng vai trò hỗ trợ, quyết định cuối cùng thuộc về con người: AI chỉ sắp xếp danh sách người hiến, chỉ cảnh báo thiếu máu, còn việc gửi lời mời, tạo đợt hiến hay xin hỗ trợ liên viện do nhân viên bệnh viện thực hiện. Thứ hai, AI chỉ được đọc dữ liệu, không được tạo hay sửa dữ liệu nghiệp vụ, và dữ liệu cá nhân chỉ được truy cập theo đúng tài khoản đang đăng nhập. Thứ ba, các điều kiện an toàn như nhóm máu, độ tuổi, khoảng cách giữa hai lần hiến luôn được kiểm tra bằng luật cố định trước khi đến AI. Thứ tư, hệ thống luôn có cơ chế fallback: khi AI gặp lỗi hoặc chưa đủ dữ liệu, hệ thống tự chuyển về phương án không dùng AI để người dùng vẫn nhận được kết quả. Cuối cùng, mô hình học máy chỉ được đưa vào sử dụng khi đã chứng minh tốt hơn phương án đơn giản trên dữ liệu kiểm tra.

## 3.2.2. Thiết kế quy trình xử lý tri thức

Tri thức trong hệ thống gồm hai nguồn: tri thức chuyên môn về hiến máu phục vụ chatbot và tri thức rút ra từ dữ liệu vận hành phục vụ các mô hình dự báo, gợi ý.

Tri thức chuyên môn được tổ chức thành một kho gồm 16 tài liệu đã được duyệt, bao gồm các chủ đề như điều kiện hiến máu, khoảng cách giữa hai lần hiến, chuẩn bị trước khi hiến, chăm sóc sau khi hiến, các loại chế phẩm máu và hướng dẫn sử dụng hệ thống. Mỗi tài liệu đều ghi rõ nguồn tham khảo, số phiên bản và ngày duyệt. Khi cần cập nhật, người quản lý sửa nội dung, tăng số phiên bản và cập nhật ngày duyệt, nhờ đó chatbot luôn trả lời dựa trên nội dung đã được kiểm duyệt. Các con số phụ thuộc cấu hình như số ngày nghỉ tối thiểu hay độ tuổi hiến máu không được ghi cố định mà lấy trực tiếp từ bảng system_settings, vì vậy khi quản trị viên thay đổi cấu hình thì câu trả lời của chatbot cũng thay đổi theo.

Để tìm tài liệu phù hợp với câu hỏi, hệ thống chuẩn hóa văn bản về dạng chữ thường không dấu, loại bỏ các từ không mang nghĩa như "tôi", "có", "không", sau đó tách thành từ đơn và cụm hai từ. Tiêu đề và từ khóa của tài liệu được tăng trọng số gấp ba lần so với phần nội dung. Mức độ liên quan giữa câu hỏi và tài liệu được tính bằng thuật toán BM25:

score(d, q) = Σ IDF(t) × f(t, d) × (k₁ + 1) / [f(t, d) + k₁ × (1 − b + b × |d| / avgdl)]

Công thức số 1 này để tính điểm liên quan của tài liệu d đối với câu hỏi q.

Trong đó f(t, d) là số lần từ t xuất hiện trong tài liệu d, |d| là độ dài tài liệu, avgdl là độ dài trung bình của các tài liệu, k₁ = 1,4 và b = 0,6 là các tham số điều chỉnh. Thành phần IDF(t) thể hiện mức độ hiếm của từ t, từ càng ít tài liệu chứa thì càng có giá trị phân biệt:

IDF(t) = ln(1 + (N − n(t) + 0,5) / (n(t) + 0,5))

Công thức số 2 này để tính trọng số của từ t, trong đó N là tổng số tài liệu và n(t) là số tài liệu chứa từ t.

Hệ thống chọn tối đa ba tài liệu có điểm cao nhất làm ngữ cảnh cho câu trả lời. Nếu không có tài liệu nào đạt ngưỡng tối thiểu, chatbot trả lời rằng chưa có thông tin thay vì để mô hình tự suy diễn.

Đối với tri thức từ dữ liệu vận hành, hệ thống không yêu cầu nhập liệu riêng mà tự rút ra từ dữ liệu nghiệp vụ hằng ngày. Dữ liệu dự báo được lấy từ sổ kho (bảng stock_txns) và các yêu cầu cần máu đã xác minh; dữ liệu gợi ý người hiến được lấy từ lịch sử các lần kêu gọi và kết quả phản hồi của người hiến. Khi dữ liệu thực tế chưa đủ, hệ thống sinh dữ liệu mô phỏng để mô hình vẫn hoạt động được và tự chuyển sang dữ liệu thật khi đã đủ. Mỗi lần huấn luyện tạo ra một phiên bản mô hình mới, phiên bản này chỉ được sử dụng khi vượt qua bước kiểm tra so với phương án đơn giản, đồng thời các phiên bản cũ vẫn được lưu lại để quản trị viên có thể khôi phục khi cần.

## 3.2.3. Thiết kế các luồng xử lý chuyên biệt

### 3.2.3.1. Luồng xử lý AI gợi ý người hiến máu phù hợp

Khi bệnh viện thiếu một nhóm máu, nhân viên cần xác định nên gửi lời kêu gọi đến những người hiến nào. Việc mời quá nhiều người gây làm phiền, trong khi mỗi người chỉ được mời một số lần giới hạn, do đó hệ thống cần ưu tiên những người có khả năng nhận lời cao nhất. Bài toán được xây dựng thành bài toán dự đoán xác suất một người hiến nhận lời, nghĩa là đăng ký đợt hiến hoặc đến hiến tại bệnh viện trong vòng 7 ngày sau khi được mời.

Đề tài không sử dụng phương pháp lọc cộng tác thường thấy ở các hệ thống gợi ý sản phẩm, vì mỗi lời kêu gọi là một sự kiện mới chưa có ai phản hồi, đồng thời mỗi người chỉ hiến tối đa khoảng bốn lần một năm nên dữ liệu tương tác rất thưa.

Luồng xử lý gồm hai bước. Bước thứ nhất là lọc bằng luật, chỉ giữ lại những người đúng nhóm máu, trong độ tuổi hiến, đã đủ thời gian nghỉ kể từ lần hiến trước, không bị mời quá dày và nằm trong bán kính đã chọn. Bước thứ hai là xếp hạng bằng mô hình học máy: mô hình chỉ sắp xếp lại thứ tự các ứng viên đã qua bước lọc, không thêm hay loại bỏ người nào.

Mỗi ứng viên được mô tả bằng các đặc trưng tính tại thời điểm gửi lời mời, gồm khoảng cách đến bệnh viện, số ngày từ lần hiến gần nhất, số lần đã hiến, nhóm máu đã được xét nghiệm hay chưa, tỷ lệ đến đúng hẹn, tỷ lệ nhận lời trong các lần kêu gọi trước, số lần đã bị kêu gọi trong 90 ngày và hoàn cảnh của lời mời như kêu gọi khẩn hay thường, gửi vào cuối tuần hay ngày thường. Hệ thống không sử dụng tuổi và giới tính làm đặc trưng để tránh phân biệt người hiến.

Mô hình hồi quy logistic tính xác suất nhận lời theo công thức:

p = 1 / (1 + e^−(w₀ + w₁x₁ + w₂x₂ + … + wₙxₙ))

Công thức số 3 này để tính xác suất người hiến nhận lời dựa trên các đặc trưng x₁, x₂, …, xₙ.

Trong đó wᵢ là trọng số mà mô hình học được từ dữ liệu, thể hiện mức độ ảnh hưởng của từng đặc trưng. Bên cạnh hồi quy logistic, hệ thống huấn luyện thêm mô hình XGBoost có khả năng học các mối quan hệ phức tạp hơn giữa các yếu tố, sau đó so sánh cả hai mô hình với cách chấm điểm theo luật đang sử dụng.

Các mô hình được đánh giá trên những lần kêu gọi ở giai đoạn sau mà mô hình chưa từng thấy, với chỉ số chính là tỷ lệ người nhận lời trong 10 người đứng đầu danh sách. Mô hình chỉ được đưa vào sử dụng khi số người nhận lời nhiều hơn cách chấm điểm luật một cách chắc chắn về mặt thống kê. Trên dữ liệu mô phỏng gồm 556 lần kêu gọi, mô hình hồi quy logistic đạt tỷ lệ nhận lời 40,1% trong 10 người đầu, cao hơn mức 38,7% của cách chấm điểm luật, và được hệ thống lựa chọn.

Khi nhân viên mở chức năng "Gợi ý người hiến", hệ thống lọc ứng viên bằng luật, tính xác suất nhận lời cho từng người và sắp xếp danh sách. Mỗi người hiến được hiển thị bằng mã ẩn danh kèm khả năng nhận lời và các yếu tố ảnh hưởng chính, nhân viên không xem được tên hay số điện thoại. Một phần nhỏ vị trí trong danh sách được dành cho người hiến mới để họ cũng có cơ hội được mời. Hệ thống tự chọn sẵn số người cần mời sao cho tổng khả năng nhận lời đủ bù số đơn vị máu đang thiếu:

p₁ + p₂ + … + pₖ ≥ số đơn vị thiếu

Công thức số 4 này để xác định số người k cần mời, trong đó pᵢ là xác suất nhận lời của người thứ i trong danh sách.

Sau khi nhân viên xác nhận, hệ thống kiểm tra lại điều kiện của từng người rồi gửi lời mời qua thông báo và email. Trong trường hợp chưa có mô hình hoặc AI bị tắt, danh sách được xếp theo cách chấm điểm luật như trước, đảm bảo chức năng luôn hoạt động.

### 3.2.3.2. Luồng xử lý AI dự báo nhu cầu sử dụng máu

Chức năng dự báo giúp bệnh viện biết trước nhóm máu và loại chế phẩm nào có nguy cơ thiếu trong 14 ngày tới, từ đó chủ động tổ chức đợt hiến hoặc kêu gọi người hiến. Trong luồng này, AI chỉ dự báo nhu cầu sử dụng, còn việc kết luận thiếu hay đủ được tính bằng quy tắc nghiệp vụ dựa trên tồn kho thực tế.

Dữ liệu lịch sử được lấy từ sổ kho, gồm các lần xuất máu cho người bệnh và các yêu cầu cần máu đã được xác minh. Các nghiệp vụ điều chuyển giữa bệnh viện và điều chỉnh kho không được tính là nhu cầu để tránh sai lệch. Từ dữ liệu này, hệ thống xây dựng các đặc trưng như nhu cầu của các ngày trước đó, trung bình 7 ngày và 28 ngày, ngày trong tuần, tháng trong năm và dịp Tết.

Mô hình XGBoost được sử dụng với hàm mục tiêu Poisson, phù hợp với dữ liệu dạng số đếm có nhiều ngày bằng 0. Để đánh giá, hệ thống so sánh mô hình với cách tính trung bình 28 ngày bằng chỉ số sai số WAPE:

WAPE = Σ|yᵢ − ŷᵢ| / Σyᵢ

Công thức số 5 này để tính sai số tương đối giữa nhu cầu thực tế và nhu cầu dự báo.

Trong đó yᵢ là nhu cầu thực tế và ŷᵢ là nhu cầu dự báo. Mô hình chỉ được sử dụng khi có sai số thấp hơn cách tính trung bình và không có xu hướng dự báo thiếu quá 5%, bởi dự báo thiếu có thể dẫn đến tình trạng thiếu máu thực tế mà hệ thống lại báo đủ.

Từ kết quả dự báo, lượng máu còn thiếu được tính theo công thức:

Thiếu dự kiến = max(0, Tổng nhu cầu dự báo 14 ngày + Nhu cầu đã lên kế hoạch − Tồn kho khả dụng)

Công thức số 6 này để tính số đơn vị máu dự kiến thiếu trong 14 ngày tới, trong đó tồn kho khả dụng bằng tồn kho thực tế trừ đi phần đang giữ chỗ cho bệnh viện khác.

Dựa trên số ngày lượng máu hiện có còn đủ dùng, hệ thống chia thành ba mức: sắp thiếu khi còn dưới 7 ngày, khi đó gợi ý mời người hiến; cần lên kế hoạch khi còn từ 7 đến 14 ngày, khi đó gợi ý tạo đợt hiến; và đủ dùng.

Quá trình dự báo được thực hiện tự động mỗi đêm và lưu kết quả vào bảng forecast_snapshots, nhờ đó trang dự báo chỉ cần đọc kết quả có sẵn mà không phải tính lại mỗi lần truy cập. Hằng ngày hệ thống so sánh kết quả dự báo với nhu cầu thực tế, chỉ huấn luyện lại mô hình khi có thêm dữ liệu mới hoặc sai số tăng lên, và tự động chuyển về cách tính trung bình 28 ngày nếu mô hình dự báo kém liên tục trong ba tuần.

### 3.2.3.3. Luồng xử lý AI Chatbot tư vấn và hướng dẫn hiến máu

Chatbot đóng vai trò như một nhân viên tư vấn, giải đáp các câu hỏi về hiến máu và hướng dẫn người dùng sử dụng hệ thống bằng tiếng Việt tự nhiên. Chatbot sử dụng mô hình ngôn ngữ lớn mã nguồn mở Qwen3 được triển khai cục bộ thông qua nền tảng Ollama, giúp hệ thống chủ động kiểm soát dữ liệu và không phụ thuộc vào dịch vụ AI bên ngoài.

Khi người dùng gửi câu hỏi, hệ thống trước tiên kiểm tra các trường hợp đặc biệt cần trả lời ngay mà không gọi đến AI, bao gồm tình huống khẩn cấp như đang chảy máu nhiều hay bất tỉnh, khi đó chatbot hướng dẫn gọi ngay 115; các câu hỏi về thông tin của người khác hoặc mua bán máu sẽ bị từ chối; các câu hỏi y khoa cá nhân như đang dùng thuốc hay có bệnh nền sẽ được khuyên hỏi ý kiến bác sĩ.

Với các câu hỏi thông thường, hệ thống áp dụng kỹ thuật RAG: tìm các tài liệu liên quan trong kho tri thức bằng thuật toán BM25 đã trình bày ở mục 3.2.2, đồng thời nếu câu hỏi liên quan đến dữ liệu của người dùng như đợt hiến gần nhất, thời điểm được hiến lại hay trạng thái đơn đăng ký thì hệ thống tra cứu dữ liệu tương ứng. Các công cụ tra cứu này chỉ được phép đọc dữ liệu của chính người đang đăng nhập và không trả về thông tin nhạy cảm như tên bệnh nhân hay số điện thoại. Thông tin tìm được cùng với các quy tắc ràng buộc được đưa vào ngữ cảnh gửi tới mô hình, yêu cầu mô hình chỉ trả lời dựa trên dữ liệu được cung cấp.

Trước khi gửi câu trả lời cho người dùng, hệ thống kiểm tra lại nội dung do AI tạo ra: các mã đơn hay mã yêu cầu xuất hiện trong câu trả lời phải có trong dữ liệu đã tra cứu, nếu không sẽ bị coi là thông tin bịa; câu trả lời không được lẫn ngôn ngữ khác; và mọi câu khẳng định người dùng đủ điều kiện hiến máu đều được bổ sung lời nhắc rằng bác sĩ khám sàng lọc mới là người quyết định.

Hệ thống được thiết kế với cơ chế fallback: trong trường hợp mô hình AI gặp lỗi, phản hồi quá chậm hoặc câu trả lời không vượt qua bước kiểm tra, chatbot tự động chuyển sang chế độ trả lời theo từ khóa, sử dụng cùng các tài liệu và dữ liệu đã tra cứu để tạo câu trả lời, giúp người dùng luôn nhận được phản hồi. Câu trả lời được hiển thị dần theo thời gian thực và kèm theo nguồn tài liệu tham khảo.

Lịch sử hội thoại của người dùng đã đăng nhập được lưu trong các bảng chat_conversations và chat_messages, chỉ chủ tài khoản được xem và tự động xóa sau 30 ngày. Để bảo vệ quyền riêng tư, nhật ký hệ thống chỉ ghi nhận loại câu hỏi và cách trả lời mà không lưu nội dung câu hỏi. Ngoài ra, mỗi người dùng chỉ được gửi tối đa 20 câu hỏi trong 5 phút nhằm tránh lạm dụng và đảm bảo hiệu năng hệ thống.
