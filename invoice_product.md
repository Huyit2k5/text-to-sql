# invoice_product: Hóa đơn chi tiết

| Tên | DataType | Ý nghĩa |
|---|---|---|
| `id` | `INT` | id sản phẩm hóa đơn |
| `invoice_id` | `INT` | id hóa đơn |
| `bill_id` | `INT` | id đơn hàng tương ứng |
| `product_id` | `INT` | id sản phẩm nếu tồn tại trên danh mục sản phẩm |
| `code` | `NVARCHAR(50)` | Mã sản phẩm |
| `position` | `INT` | Số thứ tự hiển thị trong danh sách sản phẩm |
| `feature` | `INT` | Tính chất sản phẩm<br>1: HHDV<br>2: KM<br>3: CK<br>4: Ghi chú<br>5: Hàng hóa đặc trưng |
| `name` | `NVARCHAR(400)` | Tên sản phẩm (FreeText) |
| `normalized_name` | `NVARCHAR(512)` | Tên sản phẩm đã chuẩn hóa |
| `quantity` | `DECIMAL(21,6)` | Số lượng |
| `unit` | `NVARCHAR(50)` | Đơn vị tính |
| `unit_price` | `DECIMAL(21,6)` | Đơn giá |
| `discount_amount` | `DECIMAL(21,6)` | Tổng tiền chiết khấu |
| `total_pre_tax` | `DECIMAL(21,6)` | Tổng tiền hàng trước thuế |
| `vat_rate` | `INT` | Thuế suất |
| `vat_amount` | `DECIMAL(21,6)` | Tổng tiền thuế |
| `total_amount` | `DECIMAL(21,6)` | Tổng tiền sau thuế |
| `creator` | `INT` | id user tạo |
| `updater` | `INT` | id user cập nhật |
| `create_time` | `DATETIME` | Thời gian tạo |
| `update_time` | `DATETIME` | Thời gian cập nhật |
