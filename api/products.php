<?php
require_once __DIR__ . '/../config/database.php';

function getAll() {
    $db = (new Database())->getConnection();
    $categoryId = $_GET['category_id'] ?? null;
    $keyword = $_GET['keyword'] ?? null;
    $page = max(1, (int)($_GET['page'] ?? 1));
    $limit = min(50, max(1, (int)($_GET['limit'] ?? 20)));
    $offset = ($page - 1) * $limit;

    $where = 'WHERE p.status = 1';
    $params = [];

    if ($categoryId) {
        $where .= ' AND p.category_id = :category_id';
        $params[':category_id'] = $categoryId;
    }
    if ($keyword) {
        $where .= ' AND (p.name LIKE :keyword OR p.description LIKE :keyword2)';
        $params[':keyword'] = "%$keyword%";
        $params[':keyword2'] = "%$keyword%";
    }

    $countStmt = $db->prepare("SELECT COUNT(*) FROM products p $where");
    $countStmt->execute($params);
    $total = $countStmt->fetchColumn();

    $stmt = $db->prepare("
        SELECT p.*, c.name as category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        $where
        ORDER BY p.is_hot DESC, p.sales DESC
        LIMIT $limit OFFSET $offset
    ");
    $stmt->execute($params);
    $products = $stmt->fetchAll();

    foreach ($products as &$p) {
        $p['images'] = json_decode($p['images'] ?? '[]', true);
        $p['specs'] = json_decode($p['specs'] ?? '[]', true);
        $p['price'] = (float)$p['price'];
        $p['original_price'] = (float)$p['original_price'];
        $p['rating'] = (float)$p['rating'];
    }

    echo json_encode([
        'code' => 0,
        'data' => [
            'list' => $products,
            'total' => (int)$total,
            'page' => $page,
            'limit' => $limit,
        ],
    ]);
}

function getHot() {
    $db = (new Database())->getConnection();
    $stmt = $db->query("
        SELECT p.*, c.name as category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.status = 1 AND p.is_hot = 1
        ORDER BY p.sales DESC
        LIMIT 20
    ");
    $products = $stmt->fetchAll();

    foreach ($products as &$p) {
        $p['images'] = json_decode($p['images'] ?? '[]', true);
        $p['specs'] = json_decode($p['specs'] ?? '[]', true);
        $p['price'] = (float)$p['price'];
        $p['original_price'] = (float)$p['original_price'];
        $p['rating'] = (float)$p['rating'];
    }

    echo json_encode(['code' => 0, 'data' => $products]);
}

function getOne() {
    $db = (new Database())->getConnection();
    $stmt = $db->prepare("
        SELECT p.*, c.name as category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE p.id = :id AND p.status = 1
    ");
    $stmt->execute([':id' => $_REQUEST['id']]);
    $product = $stmt->fetch();

    if (!$product) {
        http_response_code(404);
        echo json_encode(['code' => 404, 'error' => 'Product not found']);
        return;
    }

    $product['images'] = json_decode($product['images'] ?? '[]', true);
    $product['specs'] = json_decode($product['specs'] ?? '[]', true);
    $product['price'] = (float)$product['price'];
    $product['original_price'] = (float)$product['original_price'];
    $product['rating'] = (float)$product['rating'];

    echo json_encode(['code' => 0, 'data' => $product]);
}
