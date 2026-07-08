<?php
require_once __DIR__ . '/../config/database.php';

function getByUser() {
    $db = (new Database())->getConnection();
    $stmt = $db->prepare("
        SELECT ci.*, p.name as product_name, 
               JSON_UNQUOTE(JSON_EXTRACT(p.images, '$[0]')) as product_image,
               p.price as product_price
        FROM cart_items ci
        JOIN products p ON ci.product_id = p.id
        WHERE ci.user_id = :user_id
    ");
    $stmt->execute([':user_id' => $_REQUEST['user_id']]);
    echo json_encode(['code' => 0, 'data' => $stmt->fetchAll()]);
}

function add() {
    $db = (new Database())->getConnection();
    $data = json_decode(file_get_contents('php://input'), true);

    if (!$data || empty($data['user_id']) || empty($data['product_id'])) {
        http_response_code(400);
        echo json_encode(['code' => 400, 'error' => 'Missing required fields']);
        return;
    }

    // Check if already in cart
    $stmt = $db->prepare("
        SELECT id, quantity FROM cart_items 
        WHERE user_id = :uid AND product_id = :pid 
        AND (spec = :spec OR (spec IS NULL AND :spec2 IS NULL))
    ");
    $stmt->execute([
        ':uid' => $data['user_id'],
        ':pid' => $data['product_id'],
        ':spec' => $data['spec'] ?? null,
        ':spec2' => $data['spec'] ?? null,
    ]);
    $existing = $stmt->fetch();

    if ($existing) {
        $stmt = $db->prepare("UPDATE cart_items SET quantity = quantity + :qty WHERE id = :id");
        $stmt->execute([':qty' => $data['quantity'] ?? 1, ':id' => $existing['id']]);
    } else {
        $stmt = $db->prepare("
            INSERT INTO cart_items (user_id, product_id, spec, quantity) 
            VALUES (:uid, :pid, :spec, :qty)
        ");
        $stmt->execute([
            ':uid' => $data['user_id'],
            ':pid' => $data['product_id'],
            ':spec' => $data['spec'] ?? null,
            ':qty' => $data['quantity'] ?? 1,
        ]);
    }

    echo json_encode(['code' => 0, 'message' => 'Added to cart']);
}

function update() {
    $db = (new Database())->getConnection();
    $data = json_decode(file_get_contents('php://input'), true);

    if (!$data || !isset($data['id']) || !isset($data['quantity'])) {
        http_response_code(400);
        echo json_encode(['code' => 400, 'error' => 'Missing required fields']);
        return;
    }

    if ($data['quantity'] <= 0) {
        $stmt = $db->prepare("DELETE FROM cart_items WHERE id = :id");
        $stmt->execute([':id' => $data['id']]);
    } else {
        $stmt = $db->prepare("UPDATE cart_items SET quantity = :qty WHERE id = :id");
        $stmt->execute([':qty' => $data['quantity'], ':id' => $data['id']]);
    }

    echo json_encode(['code' => 0, 'message' => 'Updated']);
}

function remove() {
    $db = (new Database())->getConnection();
    $data = json_decode(file_get_contents('php://input'), true);

    if (!$data || empty($data['id'])) {
        http_response_code(400);
        echo json_encode(['code' => 400, 'error' => 'Missing id']);
        return;
    }

    $stmt = $db->prepare("DELETE FROM cart_items WHERE id = :id");
    $stmt->execute([':id' => $data['id']]);
    echo json_encode(['code' => 0, 'message' => 'Removed']);
}
