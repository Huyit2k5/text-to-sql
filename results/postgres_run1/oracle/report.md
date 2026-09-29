# Kết quả đánh giá (ORACLE, kiểm tra harness)

- Bộ đánh giá: 64 câu (60 có đáp án, 4 câu phải từ chối)
- Model: oracle, effort mặc định
- Database: PostgreSQL t2sql_app@127.0.0.1:5433/shop
- Execution accuracy tính trên các câu có đáp án; hoán vị cột và thứ tự dòng được chuẩn hóa (trừ câu yêu cầu thứ tự); 'EX nới lỏng' chấp nhận thêm cột thừa.

| Cấu hình | Execution accuracy | Dễ | Trung bình | Khó | Từ chối đúng | Lỗi thực thi | EX nới lỏng | Lời gọi LLM | Token vào/ra | Độ trễ TB | Ghi chú |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Baseline (Mức 1) | **100.0%** | 100% | 100% | 100% | 100% | 0 | 100.0% | 64 | 0/0 | 0.0s |  |
| + Mô tả cột | **100.0%** | 100% | 100% | 100% | 100% | 0 | 100.0% | 64 | 0/0 | 0.0s | +0.0 điểm so với dòng trên |
| + Few-shot | **100.0%** | 100% | 100% | 100% | 100% | 0 | 100.0% | 64 | 0/0 | 0.0s | +0.0 điểm so với dòng trên |
| + Schema linking | **100.0%** | 100% | 100% | 100% | 100% | 0 | 100.0% | 64 | 0/0 | 0.0s | +0.0 điểm so với dòng trên |
| + Tự sửa lỗi | **100.0%** | 100% | 100% | 100% | 100% | 0 | 100.0% | 64 | 0/0 | 0.0s | +0.0 điểm so với dòng trên |

## Phân tích lỗi: Baseline (Mức 1) (0 câu sai / 64)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|

## Phân tích lỗi: + Tự sửa lỗi (0 câu sai / 64)

| Nhóm lỗi | Số câu | Các câu |
|---|---|---|
