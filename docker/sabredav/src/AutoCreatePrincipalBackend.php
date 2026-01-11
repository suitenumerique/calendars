<?php
/**
 * Custom principal backend that auto-creates principals when they don't exist.
 * This allows Apache authentication to work without pre-creating principals.
 */

namespace Calendars\SabreDav;

use Sabre\DAVACL\PrincipalBackend\PDO as BasePDO;
use Sabre\DAV\MkCol;

class AutoCreatePrincipalBackend extends BasePDO
{
    /**
     * Returns a specific principal, specified by it's path.
     * Auto-creates the principal if it doesn't exist.
     *
     * @param string $path
     *
     * @return array|null
     */
    public function getPrincipalByPath($path)
    {
        $principal = parent::getPrincipalByPath($path);
        
        // If principal doesn't exist, create it automatically
        if (!$principal && strpos($path, 'principals/') === 0) {
            // Extract username from path (e.g., "principals/user@example.com" -> "user@example.com")
            $username = substr($path, strlen('principals/'));
            
            // Create principal directly in database
            // Access protected pdo property from parent
            $pdo = $this->pdo;
            $tableName = $this->tableName;
            
            try {
                $stmt = $pdo->prepare(
                    'INSERT INTO ' . $tableName . ' (uri, email, displayname) VALUES (?, ?, ?) ON CONFLICT (uri) DO NOTHING'
                );
                $stmt->execute([$path, $username, $username]);
                
                // Retry getting the principal
                $principal = parent::getPrincipalByPath($path);
            } catch (\Exception $e) {
                // If creation fails, return null
                error_log("Failed to auto-create principal: " . $e->getMessage());
                return null;
            }
        }
        
        return $principal;
    }
}
