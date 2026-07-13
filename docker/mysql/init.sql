SET NAMES utf8mb4;
USE datapilot;

CREATE TABLE users (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    city VARCHAR(50) NOT NULL,
    level VARCHAR(20) NOT NULL,
    registered_at DATE NOT NULL
) CHARACTER SET utf8mb4;

CREATE TABLE products (
    id INT PRIMARY KEY,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    brand VARCHAR(50) NOT NULL,
    cost_price DECIMAL(10, 2) NOT NULL,
    list_price DECIMAL(10, 2) NOT NULL
) CHARACTER SET utf8mb4;

CREATE TABLE orders (
    id INT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    city VARCHAR(50) NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at DATE NOT NULL,
    refund_amount DECIMAL(10, 2) NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
) CHARACTER SET utf8mb4;

CREATE TEMPORARY TABLE numbers (n INT PRIMARY KEY);
INSERT INTO numbers (n)
SELECT ones.n + tens.n * 10 + hundreds.n * 100 + 1
FROM
    (SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
     UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) ones
CROSS JOIN
    (SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
     UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) tens
CROSS JOIN
    (SELECT 0 n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
     UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9) hundreds;

INSERT INTO users (id, name, city, level, registered_at)
SELECT
    1000 + n,
    CONCAT('用户', LPAD(n, 2, '0')),
    ELT(MOD(n - 1, 12) + 1, '北京', '上海', '广州', '深圳', '杭州', '成都', '武汉', '南京', '苏州', '西安', '重庆', '长沙'),
    ELT(MOD(n - 1, 4) + 1, '普通', '银卡', '金卡', '黑金'),
    DATE_SUB(CURRENT_DATE, INTERVAL (120 + n * 7) DAY)
FROM numbers
WHERE n <= 80;

INSERT INTO products (id, product_name, category, brand, cost_price, list_price) VALUES
(1, '无线鼠标', '数码配件', 'LogiPlus', 89, 199),
(2, '机械键盘', '数码配件', 'KeyMaster', 260, 499),
(3, '蓝牙耳机', '数码配件', 'SoundBee', 180, 399),
(4, '空气炸锅', '家用电器', 'HomePro', 390, 699),
(5, '智能电饭煲', '家用电器', 'HomePro', 310, 599),
(6, '咖啡机', '家用电器', 'BeanLab', 790, 1299),
(7, '冲锋衣', '服饰鞋包', 'TrailGo', 430, 899),
(8, '跑步鞋', '服饰鞋包', 'RunPeak', 260, 599),
(9, '保温杯', '生活日用', 'DailyUp', 45, 129),
(10, '人体工学椅', '办公家具', 'WorkWell', 880, 1599),
(11, '显示器', '数码配件', 'ViewMax', 760, 1299),
(12, '移动硬盘', '数码配件', 'DataBox', 320, 699),
(13, '扫地机器人', '家用电器', 'HomePro', 1190, 2299),
(14, '净水器', '家用电器', 'PureFlow', 980, 1899),
(15, '羽绒服', '服饰鞋包', 'WarmGo', 520, 1099),
(16, '双肩包', '服饰鞋包', 'UrbanPack', 150, 399),
(17, '洗发水', '美妆个护', 'CarePlus', 38, 89),
(18, '护肤套装', '美妆个护', 'GlowLab', 210, 499),
(19, '坚果礼盒', '食品饮料', 'SnackFun', 90, 199),
(20, '咖啡豆', '食品饮料', 'BeanLab', 78, 169),
(21, '婴儿推车', '母婴用品', 'BabyJoy', 650, 1399),
(22, '儿童积木', '母婴用品', 'KidStar', 80, 199),
(23, '瑜伽垫', '运动户外', 'FitNow', 55, 129),
(24, '露营帐篷', '运动户外', 'TrailGo', 430, 899),
(25, '商务笔记本', '图书文具', 'PaperPro', 28, 69),
(26, '钢笔礼盒', '图书文具', 'WriteWell', 120, 299),
(27, '升降桌', '办公家具', 'WorkWell', 900, 1899),
(28, '文件柜', '办公家具', 'OfficePro', 300, 799),
(29, '智能手表', '数码配件', 'TechTime', 450, 999),
(30, '电动牙刷', '美妆个护', 'CarePlus', 120, 299);

INSERT INTO orders (
    id, user_id, product_id, product_name, category, city,
    amount, status, created_at, refund_amount
)
SELECT
    n,
    u.id,
    p.id,
    p.product_name,
    p.category,
    u.city,
    CASE
        WHEN MOD(n, 31) = 0 THEN 0
        ELSE ROUND(p.list_price * (0.85 + MOD(n, 51) / 100), 2)
    END,
    CASE
        WHEN MOD(n, 31) = 0 THEN 'cancelled'
        WHEN MOD(n, 19) = 0 THEN 'refunded'
        ELSE 'paid'
    END,
    DATE_SUB(CURRENT_DATE, INTERVAL MOD(n, 120) DAY),
    CASE
        WHEN MOD(n, 31) <> 0 AND MOD(n, 19) = 0
            THEN ROUND(p.list_price * (0.85 + MOD(n, 51) / 100), 2)
        ELSE 0
    END
FROM numbers
JOIN products p ON p.id = MOD(n * 7 - 1, 30) + 1
JOIN users u ON u.id = 1000 + MOD(n * 13 - 1, 80) + 1;

DROP TEMPORARY TABLE numbers;

CREATE USER IF NOT EXISTS 'datapilot_ro'@'%' IDENTIFIED BY 'datapilot123';
GRANT SELECT ON datapilot.* TO 'datapilot_ro'@'%';
