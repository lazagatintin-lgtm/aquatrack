-- =========================================================
-- AQUATRACK: JRJ PETSHOP
-- DATABASE: aquatrack_db
-- MYSQL VERSION: 8.0.46
-- PURPOSE: DATABASE STRUCTURE AND CONSTRAINTS
-- =========================================================

CREATE DATABASE IF NOT EXISTS aquatrack_db
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE aquatrack_db;


-- =========================================================
-- 1. USER MANAGEMENT
-- =========================================================

CREATE TABLE IF NOT EXISTS tbl_users (
    id INT NOT NULL AUTO_INCREMENT,
    user_code VARCHAR(20) NOT NULL,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    password VARCHAR(255) NOT NULL,
    role ENUM('admin', 'staff', 'customer') NOT NULL DEFAULT 'customer',
    profile_image_path VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_users_user_code (user_code),
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS tbl_staff_registration_approvals (
    id INT NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    approved_by INT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_staff_approval_email (email),
    CONSTRAINT fk_staff_approval_owner
        FOREIGN KEY (approved_by)
        REFERENCES tbl_users (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- 2. PRODUCT INFORMATION
-- =========================================================

CREATE TABLE IF NOT EXISTS tbl_products (
    id INT NOT NULL AUTO_INCREMENT,
    product_code VARCHAR(20) NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    description TEXT,
    image_path VARCHAR(255) DEFAULT NULL,
    price DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    quantity INT NOT NULL DEFAULT 0,
    min_stock INT NOT NULL DEFAULT 5,
    max_stock INT DEFAULT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'Available',
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_products_product_code (product_code),

    CONSTRAINT chk_products_price
        CHECK (price > 0),

    CONSTRAINT chk_products_quantity
        CHECK (quantity >= 0),

    CONSTRAINT chk_products_min_stock
        CHECK (min_stock >= 0),

    CONSTRAINT chk_products_max_stock
        CHECK (max_stock IS NULL OR max_stock >= min_stock)
) ENGINE=InnoDB;


-- =========================================================
-- 3. DAILY FISH CATALOG
-- =========================================================

CREATE TABLE IF NOT EXISTS tbl_daily_catalog (
    id INT NOT NULL AUTO_INCREMENT,
    catalog_code VARCHAR(20) NOT NULL,
    product_id INT NOT NULL,
    catalog_date DATE NOT NULL,
    available_quantity INT NOT NULL DEFAULT 0,

    PRIMARY KEY (id),
    UNIQUE KEY uq_catalog_code (catalog_code),
    UNIQUE KEY uq_catalog_product_date (product_id, catalog_date),
    KEY idx_catalog_date (catalog_date),

    CONSTRAINT chk_catalog_available_quantity
        CHECK (available_quantity >= 0),

    CONSTRAINT fk_daily_catalog_product
        FOREIGN KEY (product_id)
        REFERENCES tbl_products (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- 4. STOCK HISTORY
-- =========================================================

CREATE TABLE IF NOT EXISTS tbl_stock_history (
    id INT NOT NULL AUTO_INCREMENT,
    stock_code VARCHAR(20) NOT NULL,
    product_id INT NOT NULL,
    change_type VARCHAR(30) NOT NULL,
    previous_quantity INT NOT NULL,
    changed_quantity INT NOT NULL,
    new_quantity INT NOT NULL,
    reason VARCHAR(255) DEFAULT NULL,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_stock_history_stock_code (stock_code),
    KEY idx_stock_history_product (product_id),
    KEY idx_stock_history_date (created_at),

    CONSTRAINT chk_stock_previous_quantity
        CHECK (previous_quantity >= 0),

    CONSTRAINT chk_stock_changed_quantity
        CHECK (changed_quantity > 0),

    CONSTRAINT chk_stock_new_quantity
        CHECK (new_quantity >= 0),

    CONSTRAINT fk_stock_history_product
        FOREIGN KEY (product_id)
        REFERENCES tbl_products (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- 5. SALES ORDERS
-- =========================================================

CREATE TABLE IF NOT EXISTS tbl_sales (
    id INT NOT NULL AUTO_INCREMENT,
    order_code VARCHAR(20) NOT NULL,
    user_id INT NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    status VARCHAR(30) NOT NULL DEFAULT 'Pending',
    order_date TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_sales_order_code (order_code),
    KEY idx_sales_user (user_id),
    KEY idx_sales_order_date (order_date),
    KEY idx_sales_status (status),

    CONSTRAINT chk_sales_total_amount
        CHECK (total_amount >= 0),

    CONSTRAINT fk_sales_user
        FOREIGN KEY (user_id)
        REFERENCES tbl_users (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- 6. SALES ORDER ITEMS
-- =========================================================

CREATE TABLE IF NOT EXISTS tbl_sale_items (
    id INT NOT NULL AUTO_INCREMENT,
    item_code VARCHAR(20) NOT NULL,
    sale_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    subtotal DECIMAL(10,2) NOT NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uq_sale_items_item_code (item_code),
    KEY idx_sale_items_sale (sale_id),
    KEY idx_sale_items_product (product_id),

    CONSTRAINT chk_sale_items_quantity
        CHECK (quantity > 0),

    CONSTRAINT chk_sale_items_price
        CHECK (price >= 0),

    CONSTRAINT chk_sale_items_subtotal
        CHECK (subtotal >= 0),

    CONSTRAINT fk_sale_items_product
        FOREIGN KEY (product_id)
        REFERENCES tbl_products (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,

    CONSTRAINT fk_sale_items_sale
        FOREIGN KEY (sale_id)
        REFERENCES tbl_sales (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- 7. PAYMENT RECORDS
-- =========================================================

CREATE TABLE IF NOT EXISTS tbl_payments (
    id INT NOT NULL AUTO_INCREMENT,
    payment_code VARCHAR(20) NOT NULL,
    sale_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    payment_method VARCHAR(50) NOT NULL DEFAULT 'Cash on Pickup',
    payment_status VARCHAR(30) NOT NULL DEFAULT 'Pending',
    payment_date TIMESTAMP NULL DEFAULT NULL,
    reference_number VARCHAR(100) DEFAULT NULL,
    proof_image VARCHAR(255) DEFAULT NULL,
    verified_by INT DEFAULT NULL,
    verified_at DATETIME DEFAULT NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uq_payments_payment_code (payment_code),
    KEY idx_payments_sale (sale_id),
    KEY idx_payments_verified_by (verified_by),

    CONSTRAINT chk_payments_amount
        CHECK (amount >= 0),

    CONSTRAINT fk_payments_sale
        FOREIGN KEY (sale_id)
        REFERENCES tbl_sales (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE,

    CONSTRAINT fk_payments_verified_by
        FOREIGN KEY (verified_by)
        REFERENCES tbl_users (id)
        ON DELETE SET NULL
        ON UPDATE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- 8. INVENTORY LOSSES
-- =========================================================

CREATE TABLE IF NOT EXISTS tbl_inventory_losses (
    id INT NOT NULL AUTO_INCREMENT,
    loss_code VARCHAR(20) NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    reason VARCHAR(255) NOT NULL,
    loss_date DATE NOT NULL,
    recorded_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uq_inventory_losses_loss_code (loss_code),
    KEY idx_inventory_losses_product (product_id),
    KEY idx_inventory_losses_date (loss_date),

    CONSTRAINT chk_inventory_losses_quantity
        CHECK (quantity > 0),

    CONSTRAINT fk_inventory_losses_product
        FOREIGN KEY (product_id)
        REFERENCES tbl_products (id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
) ENGINE=InnoDB;


-- =========================================================
-- 9. EMAIL OTP VERIFICATION
-- =========================================================

CREATE TABLE IF NOT EXISTS tbl_email_otps (
    id INT NOT NULL AUTO_INCREMENT,
    otp_code VARCHAR(20) NOT NULL,
    user_id INT NOT NULL,
    otp_hash VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    is_used TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    purpose VARCHAR(30) NOT NULL DEFAULT 'login',

    PRIMARY KEY (id),
    UNIQUE KEY uq_email_otps_otp_code (otp_code),
    KEY idx_email_otps_user (user_id),
    KEY idx_email_otps_expiration (expires_at),

    CONSTRAINT chk_email_otps_attempts
        CHECK (attempts >= 0),

    CONSTRAINT fk_email_otps_user
        FOREIGN KEY (user_id)
        REFERENCES tbl_users (id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
) ENGINE=InnoDB;

-- =========================================================
-- 10. LOGIN RATE LIMITS
-- =========================================================

CREATE TABLE IF NOT EXISTS tbl_login_rate_limits (
    bucket_hash CHAR(64) NOT NULL,
    window_started_at DATETIME NOT NULL,
    failed_attempts INT NOT NULL DEFAULT 0,

    PRIMARY KEY (bucket_hash),
    KEY idx_login_rate_window (window_started_at),

    CONSTRAINT chk_login_rate_attempts
        CHECK (failed_attempts >= 0)
) ENGINE=InnoDB;


-- =========================================================
-- END OF AQUATRACK DATABASE SCHEMA
-- =========================================================