-- eShop 商城数据库结构
CREATE DATABASE IF NOT EXISTS eshop DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE eshop;

-- 分类表
CREATE TABLE categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    icon VARCHAR(10) NOT NULL DEFAULT '📦',
    sort INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 商品表
CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    price DECIMAL(10,2) NOT NULL,
    original_price DECIMAL(10,2) NOT NULL DEFAULT 0,
    images JSON,
    category_id INT NOT NULL,
    sales INT NOT NULL DEFAULT 0,
    rating DECIMAL(2,1) NOT NULL DEFAULT 5.0,
    specs JSON,
    is_hot TINYINT(1) NOT NULL DEFAULT 0,
    status TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 用户表
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    phone VARCHAR(20) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    nickname VARCHAR(50),
    avatar VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 购物车
CREATE TABLE cart_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    spec VARCHAR(50),
    quantity INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 订单表
CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_no VARCHAR(32) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    total DECIMAL(10,2) NOT NULL,
    status ENUM('pending','paid','shipped','completed','cancelled') NOT NULL DEFAULT 'pending',
    address JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 订单商品
CREATE TABLE order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    product_image VARCHAR(500),
    spec VARCHAR(50),
    price DECIMAL(10,2) NOT NULL,
    quantity INT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 初始化分类数据
INSERT INTO categories (name, icon, sort) VALUES
('手机', '📱', 1),
('电脑', '💻', 2),
('耳机', '🎧', 3),
('手表', '⌚', 4),
('平板', '📋', 5),
('相机', '📷', 6),
('配件', '🔌', 7),
('家居', '🏠', 8);

-- 初始化商品数据
INSERT INTO products (name, description, price, original_price, images, category_id, sales, rating, specs, is_hot) VALUES
('iPhone 15 Pro Max 256GB', 'A17 Pro 芯片，钛金属设计，4800 万像素主摄', 8999, 9999, '["https://picsum.photos/seed/iphone1/400/400","https://picsum.photos/seed/iphone2/400/400"]', 1, 12340, 4.8, '["256GB","512GB","1TB"]', 1),
('MacBook Pro 14" M3 Pro', '18GB 内存 / 512GB 存储，Liquid Retina XDR 显示屏', 12999, 14999, '["https://picsum.photos/seed/macbook1/400/400"]', 2, 8560, 4.9, '["18GB","36GB"]', 1),
('AirPods Pro 第二代', '自适应音频，USB-C 充电盒，主动降噪', 1799, 1899, '["https://picsum.photos/seed/airpods1/400/400"]', 3, 25600, 4.7, NULL, 1),
('Apple Watch Ultra 2', '49mm 钛金属表壳，精准双频 GPS', 6299, 6499, '["https://picsum.photos/seed/watch1/400/400"]', 4, 4320, 4.9, '["海洋表带","野径回环","高山回环"]', 1),
('iPad Pro M4 11"', '超视网膜 XDR 显示屏，M4 芯片', 7599, 8499, '["https://picsum.photos/seed/ipad1/400/400"]', 5, 6780, 4.8, '["256GB","512GB","1TB"]', 1),
('Sony A7M4 全画幅微单', '3300 万像素，4K 60p 视频', 15499, 16999, '["https://picsum.photos/seed/sony1/400/400"]', 6, 3210, 4.8, '["单机身","24-70mm套机"]', 1),
('MagSafe 充电器', '15W 无线快充，兼容 iPhone 12 及以上', 299, 329, '["https://picsum.photos/seed/magsafe/400/400"]', 7, 89000, 4.5, NULL, 0),
-- 客服账号（在 users 表加 role 字段）
ALTER TABLE users ADD COLUMN role ENUM('user','admin') NOT NULL DEFAULT 'user';

-- 聊天会话表
CREATE TABLE chat_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    user_name VARCHAR(50) NOT NULL DEFAULT '匿名用户',
    last_message TEXT,
    unread INT NOT NULL DEFAULT 0,
    status ENUM('open','closed') NOT NULL DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 聊天消息表
CREATE TABLE chat_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    sender_type ENUM('user','admin') NOT NULL,
    content TEXT NOT NULL,
    is_read TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 初始化一个测试客服账号
INSERT INTO users (phone, password, nickname, role) VALUES
('admin', '$2y$10$dummy_hash_replace_this', '客服小e', 'admin');
