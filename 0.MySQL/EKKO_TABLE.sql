DROP DATABASE IF EXISTS EKKO;
CREATE DATABASE IF NOT EXISTS EKKO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE EKKO;

DROP TABLE IF EXISTS EKKO.users;
CREATE TABLE IF NOT EXISTS EKKO.users (
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

DROP TABLE IF EXISTS EKKO.user_token;
CREATE TABLE IF NOT EXISTS EKKO.user_token (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'ID',
    user_id CHAR(7) NOT NULL COMMENT '关联用户ID',
    token VARCHAR(255) UNIQUE NOT NULL COMMENT '令牌值',
    expires_at TIMESTAMP NOT NULL COMMENT '过期时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT fk_uid FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_token (token),
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS EKKO.domain;
CREATE TABLE IF NOT EXISTS EKKO.domain (
    id CHAR(8) PRIMARY KEY COMMENT '域ID',
    create_id CHAR(7) NOT NULL COMMENT '创建者ID',
    avatar TEXT NULL COMMENT '域头像URL或Base64',
    domain_name VARCHAR(255) NOT NULL COMMENT '域名称',
    description TEXT COMMENT '域描述',
    is_public BOOLEAN DEFAULT TRUE COMMENT '是否公开域',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT fk_domain_creator FOREIGN KEY (create_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_domain_id (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS EKKO.domain_members;
CREATE TABLE IF NOT EXISTS EKKO.domain_members (
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

DROP TABLE IF EXISTS EKKO.channels;
CREATE TABLE IF NOT EXISTS EKKO.channels (
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

DROP TABLE IF EXISTS EKKO.channel_members;
CREATE TABLE IF NOT EXISTS EKKO.channel_members (
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

DROP TABLE IF EXISTS EKKO.voice_process;
CREATE TABLE IF NOT EXISTS EKKO.voice_process (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '语音记录ID',
    domain_id CHAR(8) NOT NULL COMMENT '域ID',
    channel_id BIGINT NOT NULL COMMENT '频道ID',
    member_id CHAR(7) NOT NULL COMMENT '发言人ID',
    voice_address TEXT NOT NULL COMMENT '语音文件地址',
    voice2text TEXT COMMENT '语音转文字结果',
    voice_duration INT DEFAULT 0 COMMENT '语音时长(秒)',
    audio_format VARCHAR(20) DEFAULT 'mp3' COMMENT '音频格式',
    file_size BIGINT COMMENT '文件大小(字节)',
    analysis_tags JSON COMMENT '分析标签JSON',
    sentiment_label VARCHAR(20) COMMENT '情感标签',
    confidence_score FLOAT DEFAULT 0.0 COMMENT '分析置信度',
    is_processed BOOLEAN DEFAULT FALSE COMMENT '是否已处理',
    processed_time TIMESTAMP NULL COMMENT '处理完成时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT fk_voice_domain FOREIGN KEY (domain_id) REFERENCES domain(id) ON DELETE CASCADE,
    CONSTRAINT fk_voice_channel FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    CONSTRAINT fk_voice_member FOREIGN KEY (member_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_voice_domain_channel_time (domain_id, channel_id, created_at),
    INDEX idx_voice_member_time (member_id, created_at),
    INDEX idx_voice_processed (is_processed, created_at),
    INDEX idx_voice_time (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS EKKO.voice_sessions;
CREATE TABLE IF NOT EXISTS EKKO.voice_sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '会话ID',
    domain_id CHAR(8) NOT NULL COMMENT '域ID',
    channel_id BIGINT NOT NULL COMMENT '频道ID',
    session_uuid BIGINT UNIQUE COMMENT '会话唯一标识',
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '开始时间',
    end_time TIMESTAMP NULL COMMENT '结束时间',
    total_duration INT DEFAULT 0 COMMENT '总时长(秒)',
    participant_count INT DEFAULT 0 COMMENT '参与人数',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    CONSTRAINT fk_session_domain FOREIGN KEY (domain_id) REFERENCES domain(id) ON DELETE CASCADE,
    CONSTRAINT fk_session_channel FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    INDEX idx_session_time (start_time, end_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS EKKO.transcript_sessions;
CREATE TABLE IF NOT EXISTS EKKO.transcript_sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'Transcript session ID',
    channel_id BIGINT NOT NULL COMMENT 'Channel ID',
    started_by CHAR(7) NOT NULL COMMENT 'Session owner user ID',
    status ENUM('active', 'processing', 'completed', 'failed') DEFAULT 'active' COMMENT 'Transcript session status',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Session start time',
    ended_at TIMESTAMP NULL COMMENT 'Session end time',
    last_error TEXT NULL COMMENT 'Last processing error',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Created at',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Updated at',
    CONSTRAINT fk_transcript_session_channel FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    CONSTRAINT fk_transcript_session_user FOREIGN KEY (started_by) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_transcript_session_channel (channel_id),
    INDEX idx_transcript_session_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DROP TABLE IF EXISTS EKKO.transcript_segments;
CREATE TABLE IF NOT EXISTS EKKO.transcript_segments (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'Transcript segment ID',
    session_id BIGINT NOT NULL COMMENT 'Transcript session ID',
    user_id CHAR(7) NOT NULL COMMENT 'Speaker user ID',
    seq_no INT NOT NULL COMMENT 'Per-session sequence number',
    start_ms INT NOT NULL COMMENT 'Segment start timestamp in ms',
    end_ms INT NOT NULL COMMENT 'Segment end timestamp in ms',
    text TEXT NOT NULL COMMENT 'Transcript text',
    is_final BOOLEAN DEFAULT TRUE COMMENT 'Whether the segment is finalized',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Created at',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Updated at',
    CONSTRAINT fk_transcript_segment_session FOREIGN KEY (session_id) REFERENCES transcript_sessions(id) ON DELETE CASCADE,
    CONSTRAINT fk_transcript_segment_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_transcript_segment_session (session_id),
    INDEX idx_transcript_segment_user (user_id),
    INDEX idx_transcript_segment_seq (session_id, seq_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
