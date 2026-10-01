### Bộ dev

| Cấu hình | EX trung bình | min - max | Dễ | TB | Khó | Lời gọi LLM | Độ trễ TB | Chặn nặng | Soát báo sai | Câu bật reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| Không quy tắc nghiệp vụ, không lịch sử | **89.7%** | 89.7 - 89.7 | 100% | 100% | 70% | 66 | 6.2s | 0.0 | 0.0 | 0 |
| Không quy tắc + tri thức từ lịch sử | **89.7%** | 89.7 - 89.7 | 100% | 100% | 70% | 64 | 8.1s | 0.0 | 0.0 | 0 |
| + Danh mục, gợi ý lỗi | **91.4%** | 91.4 - 91.4 | 100% | 100% | 75% | 66 | 10.5s | 0.0 | 0.0 | 0 |

### Bộ holdout

| Cấu hình | EX trung bình | min - max | Dễ | TB | Khó | Lời gọi LLM | Độ trễ TB | Chặn nặng | Soát báo sai | Câu bật reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| Không quy tắc nghiệp vụ, không lịch sử | **86.2%** | 85.0 - 87.5 | 100% | 79% | 84% | 44 | 14.5s | 0.0 | 0.0 | 0 |
| Không quy tắc + tri thức từ lịch sử | **90.0%** | 90.0 - 90.0 | 100% | 86% | 88% | 45 | 11.9s | 0.0 | 0.0 | 0 |
| + Danh mục, gợi ý lỗi | **91.3%** | 90.0 - 92.5 | 100% | 79% | 97% | 46 | 8.5s | 0.0 | 0.0 | 0 |
