CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    level TEXT NOT NULL,
    registered_at DATE NOT NULL
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT NOT NULL,
    cost_price NUMERIC(10, 2) NOT NULL,
    list_price NUMERIC(10, 2) NOT NULL
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    city TEXT NOT NULL,
    amount NUMERIC(10, 2) NOT NULL,
    status TEXT NOT NULL,
    created_at DATE NOT NULL,
    refund_amount NUMERIC(10, 2) NOT NULL DEFAULT 0
);

INSERT INTO users (id, name, city, level, registered_at)
SELECT
    1000 + i,
    '用户' || LPAD(i::TEXT, 2, '0'),
    (ARRAY['北京', '上海', '广州', '深圳', '杭州', '成都', '武汉', '南京', '苏州', '西安', '重庆', '长沙'])[((i - 1) % 12) + 1],
    (ARRAY['普通', '银卡', '金卡', '黑金'])[((i - 1) % 4) + 1],
    CURRENT_DATE - (120 + i * 7) * INTERVAL '1 day'
FROM generate_series(1, 80) AS i;

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
    gs,
    u.id,
    p.id,
    p.product_name,
    p.category,
    u.city,
    CASE
        WHEN gs % 31 = 0 THEN 0
        ELSE ROUND(p.list_price * (0.85 + (gs % 51)::NUMERIC / 100), 2)
    END AS amount,
    CASE
        WHEN gs % 31 = 0 THEN 'cancelled'
        WHEN gs % 19 = 0 THEN 'refunded'
        ELSE 'paid'
    END AS status,
    CURRENT_DATE - (gs % 120) * INTERVAL '1 day' AS created_at,
    CASE
        WHEN gs % 31 <> 0 AND gs % 19 = 0 THEN ROUND(p.list_price * (0.85 + (gs % 51)::NUMERIC / 100), 2)
        ELSE 0
    END AS refund_amount
FROM generate_series(1, 1000) AS gs
JOIN products p ON p.id = (((gs * 7 - 1) % 30) + 1)
JOIN users u ON u.id = 1000 + (((gs * 13 - 1) % 80) + 1);
