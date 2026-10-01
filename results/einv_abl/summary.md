### Bộ dev

| Cấu hình | EX trung bình | min - max | Dễ | TB | Khó | Lời gọi LLM | Độ trễ TB | Chặn nặng | Soát báo sai | Câu bật reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| Khởi đầu lạnh + chỉ thống kê quy ước | **82.8%** | 82.8 - 82.8 | 94% | 98% | 57% | 66 | 5.0s | 0.0 | 0.0 | 0 |
| Khởi đầu lạnh + chỉ truy vấn minh họa | **78.4%** | 77.6 - 79.3 | 88% | 91% | 57% | 66 | 4.1s | 0.0 | 0.0 | 0 |

### Bộ holdout

| Cấu hình | EX trung bình | min - max | Dễ | TB | Khó | Lời gọi LLM | Độ trễ TB | Chặn nặng | Soát báo sai | Câu bật reasoning |
|---|---|---|---|---|---|---|---|---|---|---|
| Khởi đầu lạnh + chỉ thống kê quy ước | **85.0%** | 82.5 - 87.5 | 100% | 86% | 75% | 48 | 6.5s | 0.0 | 0.0 | 0 |
| Khởi đầu lạnh + chỉ truy vấn minh họa | **82.5%** | 82.5 - 82.5 | 90% | 86% | 75% | 47 | 6.9s | 0.0 | 0.0 | 0 |
