DROP DATABASE IF EXISTS ekko;
CREATE DATABASE IF NOT EXISTS ekko CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ekko;

DROP TABLE IF EXISTS ekko.user_channel_voice_profile;
DROP TABLE IF EXISTS ekko.voice_messages;
DROP TABLE IF EXISTS ekko.channel_members;
DROP TABLE IF EXISTS ekko.channels;
DROP TABLE IF EXISTS ekko.domain_members;
DROP TABLE IF EXISTS ekko.domain;
DROP TABLE IF EXISTS ekko.user_token;
DROP TABLE IF EXISTS ekko.users;

CREATE TABLE IF NOT EXISTS ekko.users (
    id CHAR(7) PRIMARY KEY COMMENT '用户ID',
    avatar TEXT NULL COMMENT '头像URL',
    nick_name VARCHAR(20) NOT NULL COMMENT '昵称',
    pwd VARCHAR(255) NOT NULL COMMENT '密码',
    email VARCHAR(255) UNIQUE COMMENT '邮箱',
    last_online_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后在线时间',
    voice_settings JSON DEFAULT NULL COMMENT '语音设置JSON',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_user_email (email),
    INDEX idx_user_id (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ekko.user_token (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '令牌ID',
    user_id CHAR(7) NOT NULL COMMENT '关联用户ID',
    token VARCHAR(255) UNIQUE NOT NULL COMMENT '令牌值',
    expires_at TIMESTAMP NOT NULL COMMENT '过期时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT fk_uid FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_token (token),
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ekko.domain (
    id CHAR(8) PRIMARY KEY COMMENT '域ID',
    create_id CHAR(7) NOT NULL COMMENT '创建者ID',
    avatar TEXT NULL COMMENT '域头像URL',
    domain_name VARCHAR(255) NOT NULL COMMENT '域名称',
    description TEXT COMMENT '域描述',
    is_public BOOLEAN DEFAULT TRUE COMMENT '是否公开域',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT fk_domain_creator FOREIGN KEY (create_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_domain_id (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ekko.domain_members (
    domain_id CHAR(8) NOT NULL COMMENT '域ID',
    member_id CHAR(7) NOT NULL COMMENT '成员ID',
    alias VARCHAR(50) NULL COMMENT '域内别名',
    join_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '加入时间',
    role ENUM('owner', 'admin', 'member') DEFAULT 'member' COMMENT '成员角色',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT pk_domain_member PRIMARY KEY (domain_id, member_id),
    CONSTRAINT fk_domain_members_domain FOREIGN KEY (domain_id) REFERENCES domain(id) ON DELETE CASCADE,
    CONSTRAINT fk_domain_members_user FOREIGN KEY (member_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_domain_member (member_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ekko.channels (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '频道ID',
    domain_id CHAR(8) NOT NULL COMMENT '所属域ID',
    channel_name VARCHAR(255) NOT NULL COMMENT '频道名称',
    description TEXT COMMENT '频道描述',
    create_id CHAR(7) NOT NULL COMMENT '创建者ID',
    max_capacity INT DEFAULT 10 COMMENT '最大容量',
    current_voice_count INT DEFAULT 0 COMMENT '当前语音人数',
    channel_type ENUM('voice', 'text', 'both') DEFAULT 'voice' COMMENT '频道类型',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT fk_channel_domain FOREIGN KEY (domain_id) REFERENCES domain(id) ON DELETE CASCADE,
    CONSTRAINT fk_channel_creator FOREIGN KEY (create_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_channel_domain (domain_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ekko.channel_members (
    channel_id BIGINT NOT NULL COMMENT '频道ID',
    member_id CHAR(7) NOT NULL COMMENT '成员ID',
    join_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '加入时间',
    microphone_state BOOLEAN DEFAULT FALSE COMMENT '麦克风状态',
    speaker_state BOOLEAN DEFAULT TRUE COMMENT '扬声器状态',
    last_active_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后活跃时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT pk_channel_member PRIMARY KEY (channel_id, member_id),
    CONSTRAINT fk_channel_member_channel FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    CONSTRAINT fk_channel_member_user FOREIGN KEY (member_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_channel_member_user (member_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ekko.voice_messages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '语音消息ID',
    channel_id BIGINT NOT NULL COMMENT '频道ID',
    user_id CHAR(7) NOT NULL COMMENT '发送者用户ID',
    client_message_id VARCHAR(64) NULL COMMENT '客户端消息ID，用于去重',
    audio_path TEXT NOT NULL COMMENT '音频存储路径',
    audio_duration_ms INT DEFAULT 0 COMMENT '音频时长，毫秒',
    transcript_text TEXT NULL COMMENT '可选转写文本',
    avg_amplitude DOUBLE NULL COMMENT '当前句子的平均绝对振幅',
    avg_frequency DOUBLE NULL COMMENT '当前句子的包络波峰每秒个数',
    avg_char_rate DOUBLE NULL COMMENT '当前句子的转写文本每秒字数',
    is_excited BOOLEAN NOT NULL DEFAULT FALSE COMMENT '当前句子是否判定为激动发言',
    transcription_status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '异步转写状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT fk_voice_message_channel FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    CONSTRAINT fk_voice_message_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_voice_message_channel_created (channel_id, created_at),
    INDEX idx_voice_message_user_created (user_id, created_at),
    INDEX idx_voice_message_client_id (client_message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ekko.user_channel_voice_profile (
    channel_id BIGINT NOT NULL COMMENT '频道ID',
    user_id CHAR(7) NOT NULL COMMENT '用户ID',
    baseline_avg_amplitude DOUBLE NOT NULL DEFAULT 0 COMMENT '前N条样本的平均绝对振幅均值',
    baseline_avg_frequency DOUBLE NOT NULL DEFAULT 0 COMMENT '前N条样本的包络波峰频率均值',
    baseline_avg_char_rate DOUBLE NOT NULL DEFAULT 0 COMMENT '前N条样本的文本字速均值',
    baseline_sample_count INT NOT NULL DEFAULT 0 COMMENT '已纳入基线的样本数',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT pk_user_channel_voice_profile PRIMARY KEY (channel_id, user_id),
    CONSTRAINT fk_voice_profile_channel FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    CONSTRAINT fk_voice_profile_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_voice_profile_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
