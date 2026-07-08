<?php
require_once __DIR__ . '/../config/database.php';

function getAll() {
    $db = (new Database())->getConnection();
    $stmt = $db->query("SELECT * FROM categories ORDER BY sort ASC");
    echo json_encode(['code' => 0, 'data' => $stmt->fetchAll()]);
}
