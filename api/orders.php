<?php
require_once __DIR__ . '/../config/database.php';

function getByUser() {
    $db = (new Database())->getConnection();
    $stmt = $db->prepare("
        SELECT * FROM orders 
        WHERE user_id = :uid 
        ORDER BY created_at DESC
    ");
    $stmt->execute([':uid' => $_REQUEST['user_id']]);
    $orders = $stmt->fetchAll();

    foreach ($orders as &$order) {
        $order['total'] = (float)$order['total'];
        $order['address'] = json_decode($order['address'] ?? '{}', true);

        // Get order items
        $itemStmt = $db->prepare("SELECT * FROM order_items WHERE order_id = :oid");
        $itemStmt->execute([':oid' => $order['id']]);
        $order['items'] = $itemStmt->fetchAll();
        foreach ($order['items'] as &$item) {
            $item['price'] = (float)$item['price'];
        }
    }

    echo json_encode(['code' => 0, 'data' => $orders]);
}

function create() {
    $db = (new Database())->getConnection();
    $data = json_decode(file_get_contents('php://input'), true);

    if (!$data || empty($data['user_id']) || empty($data['items'])) {
        http_response_code(400);
        echo json_encode(['code' => 400, 'error' => 'Missing required fields']);
        return;
    }

    $db->beginTransaction();
    try {
        // Calculate total
        $total = 0;
        foreach ($data['items'] as $item) {
            $stmt = $db->prepare("SELECT price, name, JSON_UNQUOTE(JSON_EXTRACT(images, '$[0]')) as img FROM products WHERE id = :id");
            $stmt->execute([':id' => $item['product_id']]);
            $product = $stmt->fetch();
            if (!$product) throw new Exception("Product {$item['product_id']} not found");
            $total += $product['price'] * $item['quantity'];
        }

        // Create order
        $orderNo = date('YmdHis') . rand(1000, 9999);
        $stmt = $db->prepare("
            INSERT INTO orders (order_no, user_id, total, status, address) 
            VALUES (:no, :uid, :total, 'pending', :addr)
        ");
        $stmt->execute([
            ':no' => $orderNo,
            ':uid' => $data['user_id'],
            ':total' => $total,
            ':addr' => json_encode($data['address'] ?? new stdClass()),
        ]);
        $orderId = $db->lastInsertId();

        // Create order items
        foreach ($data['items'] as $item) {
            $stmt = $db->prepare("SELECT price, name, JSON_UNQUOTE(JSON_EXTRACT(images, '$[0]')) as img FROM products WHERE id = :id");
            $stmt->execute([':id' => $item['product_id']]);
            $product = $stmt->fetch();

            $stmt = $db->prepare("
                INSERT INTO order_items (order_id, product_id, product_name, product_image, spec, price, quantity)
                VALUES (:oid, :pid, :name, :img, :spec, :price, :qty)
            ");
            $stmt->execute([
                ':oid' => $orderId,
                ':pid' => $item['product_id'],
                ':name' => $product['name'],
                ':img' => $product['img'],
                ':spec' => $item['spec'] ?? null,
                ':price' => $product['price'],
                ':qty' => $item['quantity'],
            ]);
        }

        // Clear cart
        $stmt = $db->prepare("DELETE FROM cart_items WHERE user_id = :uid");
        $stmt->execute([':uid' => $data['user_id']]);

        $db->commit();
        echo json_encode(['code' => 0, 'data' => ['order_id' => $orderId, 'order_no' => $orderNo, 'total' => $total]]);
    } catch (Exception $e) {
        $db->rollBack();
        http_response_code(500);
        echo json_encode(['code' => 500, 'error' => $e->getMessage()]);
    }
}
