<?php
require_once __DIR__ . '/../config/database.php';

function register() {
    $db = (new Database())->getConnection();
    $data = json_decode(file_get_contents('php://input'), true);

    if (!$data || empty($data['phone']) || empty($data['password'])) {
        http_response_code(400);
        echo json_encode(['code' => 400, 'error' => 'Phone and password required']);
        return;
    }

    // Check duplicate
    $stmt = $db->prepare("SELECT id FROM users WHERE phone = :phone");
    $stmt->execute([':phone' => $data['phone']]);
    if ($stmt->fetch()) {
        http_response_code(409);
        echo json_encode(['code' => 409, 'error' => 'Phone already registered']);
        return;
    }

    $stmt = $db->prepare("
        INSERT INTO users (phone, password, nickname) 
        VALUES (:phone, :pass, :nick)
    ");
    $stmt->execute([
        ':phone' => $data['phone'],
        ':pass' => password_hash($data['password'], PASSWORD_BCRYPT),
        ':nick' => $data['nickname'] ?? '用户' . substr($data['phone'], -4),
    ]);

    $userId = $db->lastInsertId();
    echo json_encode([
        'code' => 0,
        'data' => [
            'id' => $userId,
            'phone' => $data['phone'],
            'nickname' => $data['nickname'] ?? '用户' . substr($data['phone'], -4),
        ],
    ]);
}

function login() {
    $db = (new Database())->getConnection();
    $data = json_decode(file_get_contents('php://input'), true);

    if (!$data || empty($data['phone']) || empty($data['password'])) {
        http_response_code(400);
        echo json_encode(['code' => 400, 'error' => 'Phone and password required']);
        return;
    }

    $stmt = $db->prepare("SELECT * FROM users WHERE phone = :phone");
    $stmt->execute([':phone' => $data['phone']]);
    $user = $stmt->fetch();

    if (!$user || !password_verify($data['password'], $user['password'])) {
        http_response_code(401);
        echo json_encode(['code' => 401, 'error' => 'Invalid credentials']);
        return;
    }

    // Simple token (use JWT in production)
    $token = bin2hex(random_bytes(32));

    echo json_encode([
        'code' => 0,
        'data' => [
            'id' => $user['id'],
            'phone' => $user['phone'],
            'nickname' => $user['nickname'],
            'avatar' => $user['avatar'],
            'token' => $token,
        ],
    ]);
}
