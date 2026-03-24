CREATE DATABASE IF NOT EXISTS finance_hub
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'joey'@'%' IDENTIFIED WITH mysql_native_password BY 'Joey@2026!';
GRANT ALL PRIVILEGES ON finance_hub.* TO 'joey'@'%';
FLUSH PRIVILEGES;

USE finance_hub;

CREATE TABLE IF NOT EXISTS finance_users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(120) NOT NULL UNIQUE,
    password_plain VARCHAR(255) NULL,
    password_hash VARCHAR(255) NULL,
    display_name VARCHAR(120) NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at DATETIME NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS finance_accounts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_name VARCHAR(120) NOT NULL,
    account_type VARCHAR(50) NOT NULL,
    currency VARCHAR(12) NOT NULL DEFAULT 'CNY',
    balance DECIMAL(14, 2) NOT NULL DEFAULT 0,
    institution VARCHAR(120),
    color_hex VARCHAR(20) DEFAULT '#15b79e',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS finance_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    account_id INT NULL,
    direction VARCHAR(20) NOT NULL,
    category VARCHAR(80) NOT NULL,
    amount DECIMAL(14, 2) NOT NULL,
    currency VARCHAR(12) NOT NULL DEFAULT 'CNY',
    note TEXT,
    merchant VARCHAR(120),
    happened_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_finance_transactions_happened_at (happened_at),
    INDEX idx_finance_transactions_direction (direction),
    CONSTRAINT fk_finance_transactions_account
      FOREIGN KEY (account_id) REFERENCES finance_accounts(id)
      ON DELETE SET NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS finance_budgets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category VARCHAR(80) NOT NULL,
    month_key VARCHAR(7) NOT NULL,
    planned_amount DECIMAL(14, 2) NOT NULL DEFAULT 0,
    spent_amount DECIMAL(14, 2) NOT NULL DEFAULT 0,
    alert_ratio DECIMAL(5, 2) NOT NULL DEFAULT 0.85,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_finance_budget_month_category (month_key, category)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS finance_snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    net_worth DECIMAL(14, 2) NOT NULL DEFAULT 0,
    cash_balance DECIMAL(14, 2) NOT NULL DEFAULT 0,
    investment_balance DECIMAL(14, 2) NOT NULL DEFAULT 0,
    debt_balance DECIMAL(14, 2) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_finance_snapshot_date (snapshot_date)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
