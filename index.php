<?php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$uri = rtrim($uri, '/');
$method = $_SERVER['REQUEST_METHOD'];

// Simple router
$routes = [
    'GET' => [
        '/api/products' => 'api/products.php@getAll',
        '/api/products/hot' => 'api/products.php@getHot',
        '/api/categories' => 'api/categories.php@getAll',
    ],
    'POST' => [
        '/api/cart' => 'api/cart.php@add',
        '/api/orders' => 'api/orders.php@create',
        '/api/user/login' => 'api/user.php@login',
        '/api/user/register' => 'api/user.php@register',
    ],
    'PUT' => [
        '/api/cart' => 'api/cart.php@update',
    ],
    'DELETE' => [
        '/api/cart' => 'api/cart.php@remove',
    ],
];

// Match static routes first
if (isset($routes[$method][$uri])) {
    list($file, $action) = explode('@', $routes[$method][$uri]);
    require_once __DIR__ . '/' . $file;
    $action();
    exit;
}

// Match /api/products/{id}
if (preg_match('#^/api/products/(\d+)$#', $uri, $matches)) {
    $_REQUEST['id'] = $matches[1];
    require_once __DIR__ . '/api/products.php';
    getOne();
    exit;
}

// Match /api/cart/{user_id}
if (preg_match('#^/api/cart/(\d+)$#', $uri, $matches)) {
    $_REQUEST['user_id'] = $matches[1];
    require_once __DIR__ . '/api/cart.php';
    getByUser();
    exit;
}

// Match /api/orders/{user_id}
if (preg_match('#^/api/orders/(\d+)$#', $uri, $matches)) {
    $_REQUEST['user_id'] = $matches[1];
    require_once __DIR__ . '/api/orders.php';
    getByUser();
    exit;
}

http_response_code(404);
echo json_encode(['error' => 'Not found', 'uri' => $uri]);
