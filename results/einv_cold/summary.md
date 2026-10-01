### Bộ dev

| Cấu hình | EX trung bình | min - max | Dễ | TB | Khó | Lời gọi LLM | Độ trễ TB | Chặn nặng | Soát báo sai | Câu bật reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| Khởi đầu lạnh (không quy tắc, không few-shot) | **56.9%** | 56.9 - 56.9 | 81% | 61% | 32% | 68 | 10.6s | 0.0 | 0.0 | 0 |
| Khởi đầu lạnh + tri thức từ lịch sử | **83.6%** | 82.8 - 84.5 | 94% | 95% | 62% | 67 | 14.8s | 0.0 | 0.0 | 0 |

### Bộ holdout

| Cấu hình | EX trung bình | min - max | Dễ | TB | Khó | Lời gọi LLM | Độ trễ TB | Chặn nặng | Soát báo sai | Câu bật reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| Khởi đầu lạnh (không quy tắc, không few-shot) | **65.0%** | 65.0 - 65.0 | 90% | 71% | 44% | 48 | 10.7s | 0.0 | 0.0 | 0 |
| Khởi đầu lạnh + tri thức từ lịch sử | **86.2%** | 85.0 - 87.5 | 100% | 86% | 78% | 44 | 11.8s | 0.0 | 0.0 | 0 |
