# invoice: Hóa đơn

| Tên | DataType | Ý nghĩa |
|---|---|---|
| `id` | `INT` | id Hóa đơn |
| `company_id` | `INT` | id công ty |
| `bill_id` | `INT` | id đơn hàng tương ứng |
| `customer_id` | `INT` | id khách hàng nếu tồn tại trên danh mục khách hàng |
| `customer_code` | `NVARCHAR(50)` | Mã khách hàng |
| `customer_name` | `NVARCHAR(400)` | Tên khách hàng (FreeText) |
| `customer_normalized_name` | `NVARCHAR(512)` | Tên đã chuẩn hóa |
| `customer_address` | `NVARCHAR(400)` | Địa chỉ khách hàng |
| `customer_taxcode` | `NVARCHAR(14)` | Mã số thuế |
| `id_number` | `VARCHAR(20)` | Số căn cước công dân |
| `customer_phone` | `VARCHAR(20)` | Số điện thoại |
| `pattern` | `VARCHAR(50)` | Ký hiệu hóa đơn |
| `no` | `INT` | Số hóa đơn |
| `arising_date` | `VARCHAR(10)` | Ngày hóa đơn |
| `publish_date` | `VARCHAR(10)` | Ngày phát hành hóa đơn |
| `payment_method` | `NVARCHAR(50)` | Hình thức thanh toán |
| `exchange_rate` |  | Mặc định = 1, Tỷ giá |
| `currency_unit` |  | Mặc định = VND, Loại tiền |
| `amount` | `DECIMAL(21,6)` | Tổng tiền sản phẩm (chưa trừ chiết khấu, giảm giá) |
| `discount_amount` | `DECIMAL(21,6)` | Tổng tiền chiết khấu |
| `total_pre_tax` | `DECIMAL(21,6)` | Tổng tiền hàng trước thuế |
| `vat_rate` | `INT` | Thuế suất |
| `vat_amount` | `DECIMAL(21,6)` | Tổng tiền thuế |
| `total_amount` | `DECIMAL(21,6)` | Tổng tiền sau thuế |
| `type` | `INT` | Loại hóa đơn:<br>-1: Chờ ký<br>0: Hóa đơn thông thường (mặc định)<br>1: Hóa đơn thay thế<br>2: Hóa đơn điều chỉnh tăng<br>3: Hóa đơn điều chỉnh giảm<br>4: Hóa đơn điều chỉnh thông tin<br>5: Hóa đơn gửi đi phát hành |
| `status` | `INT` | Trạng thái hóa đơn:<br>-1: Hóa đơn chờ ký<br>null : hóa đơn chưa phát hành<br>0: Hóa đơn mới tạo lập<br>1: Hóa đơn có chữ ký số<br>2: Hóa đơn đã khai báo thuế<br>3: Hóa đơn bị thay thế<br>4: Hóa đơn bị điều chỉnh<br>5: Hóa đơn bị hủy (Không còn sử dụng)<br>6: Hóa đơn đã duyệt (Không sử dụng) |
| `tax_check_status` | `INT` | Trạng thái của Tổng cục thuế<br>-1 Đang kiểm tra<br>null : chưa phát hành<br>-2 Không hợp lệ<br>1 Hợp lệ |
| `tax_authority_code` | `VARCHAR(23)` | Mã cơ quan thuế |
| `tax_error_message` | `NVARCHAR(255)` | Lỗi của tổng cục thuế trả về |
| `ikey` | `VARCHAR(100)` | Ikey hóa đơn |
| `refikey` | `VARCHAR(100)` | ikey của hóa đơn thay thế |
| `extra` | `NTEXT` | Trường mở rộng |
| `creator` | `INT` | id user tạo bill |
| `updater` | `INT` | id user cập nhật |
| `create_time` | `DATETIME` | Thời gian tạo |
| `update_time` | `DATETIME` | Thời gian cập nhật |
