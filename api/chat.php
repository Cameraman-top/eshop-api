<?php
require_once __DIR__ . '/../config/database.php';

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(200); exit; }

$method = $_SERVER['REQUEST_METHOD'];
$action = $_GET['action'] ?? '';

try {
    $db = Database::getInstance();

    switch ($action) {
        case 'sessions':
            // 获取所有会话列表（客服后台用）
            if ($method === 'GET') {
                $sessions = $db->fetchAll(
                    "SELECT s.*, 
                        (SELECT COUNT(*) FROM chat_messages WHERE session_id = s.id AND sender_type = 'user' AND is_read = 0) as unread
                     FROM chat_sessions s 
                     WHERE s.status = 'open' 
                     ORDER BY s.updated_at DESC"
                );
                echo json_encode(['code' => 0, 'data' => $sessions]);
            }
            break;

        case 'messages':
            $sessionId = $_GET['session_id'] ?? 0;
            if ($method === 'GET') {
                // 获取会话消息
                $messages = $db->fetchAll(
                    "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
                    [$sessionId]
                );
                // 标记为已读
                $db->execute(
                    "UPDATE chat_messages SET is_read = 1 WHERE session_id = ? AND sender_type = 'user'",
                    [$sessionId]
                );
                $db->execute(
                    "UPDATE chat_sessions SET unread = 0 WHERE id = ?",
                    [$sessionId]
                );
                echo json_encode(['code' => 0, 'data' => $messages]);
            } elseif ($method === 'POST') {
                // 发送消息
                $input = json_decode(file_get_contents('php://input'), true);
                $senderType = $input['sender_type'] ?? 'user';
                $content = $input['content'] ?? '';
                
                if (empty($content)) {
                    http_response_code(400);
                    echo json_encode(['code' => 1, 'msg' => '消息不能为空']);
                    exit;
                }

                // 如果没有 session_id，创建新会话
                if (empty($sessionId)) {
                    $userName = $input['user_name'] ?? '匿名用户';
                    $db->execute(
                        "INSERT INTO chat_sessions (user_name, last_message) VALUES (?, ?)",
                        [$userName, mb_substr($content, 0, 100)]
                    );
                    $sessionId = $db->lastInsertId();
                } else {
                    $db->execute(
                        "UPDATE chat_sessions SET last_message = ?, updated_at = NOW() WHERE id = ?",
                        [mb_substr($content, 0, 100), $sessionId]
                    );
                }

                // 如果是用户消息，增加未读数
                if ($senderType === 'user') {
                    $db->execute("UPDATE chat_sessions SET unread = unread + 1 WHERE id = ?", [$sessionId]);
                }

                $db->execute(
                    "INSERT INTO chat_messages (session_id, sender_type, content) VALUES (?, ?, ?)",
                    [$sessionId, $senderType, $content]
                );

                echo json_encode([
                    'code' => 0,
                    'data' => [
                        'session_id' => $sessionId,
                        'id' => $db->lastInsertId()
                    ]
                ]);
            }
            break;

        case 'close':
            // 关闭会话
            if ($method === 'POST') {
                $input = json_decode(file_get_contents('php://input'), true);
                $sessionId = $input['session_id'] ?? 0;
                $db->execute("UPDATE chat_sessions SET status = 'closed' WHERE id = ?", [$sessionId]);
                echo json_encode(['code' => 0, 'msg' => '已关闭']);
            }
            break;

        case 'unread':
            // 获取未读会话数
            if ($method === 'GET') {
                $count = $db->fetchOne(
                    "SELECT COUNT(*) as cnt FROM chat_sessions WHERE unread > 0 AND status = 'open'"
                );
                echo json_encode(['code' => 0, 'data' => ['count' => (int)$count['cnt']]]);
            }
            break;

        default:
            http_response_code(400);
            echo json_encode(['code' => 1, 'msg' => '未知操作']);
    }
} catch (Exception $e) {
    http_response_code(500);
    echo json_encode(['code' => 1, 'msg' => $e->getMessage()]);
}
