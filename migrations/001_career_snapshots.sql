CREATE TABLE IF NOT EXISTS career_snapshots (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 user_id INT NOT NULL,
 workspace_id CHAR(36) NOT NULL,
 resume_id INT NOT NULL,
 job_description_id INT NOT NULL,
 action VARCHAR(32) NOT NULL,
 payload_hash CHAR(64) NOT NULL,
 report_json LONGTEXT NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_user_payload (user_id, payload_hash),
 KEY ix_user_workspace (user_id, workspace_id, id),
 KEY ix_user_history (user_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
