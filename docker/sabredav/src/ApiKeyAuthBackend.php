<?php
/**
 * Custom authentication backend that supports API key and header-based authentication.
 * 
 * This backend authenticates users via:
 * - API key authentication: X-Api-Key header and X-Forwarded-User header
 * 
 * This allows Django to authenticate with CalDAV server using an API key.
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Auth\Backend\BackendInterface;
use Sabre\HTTP\RequestInterface;
use Sabre\HTTP\ResponseInterface;

class ApiKeyAuthBackend implements BackendInterface
{
    /**
     * Expected API key for outbound authentication (from Django to CalDAV)
     * @var string
     */
    private $apiKey;

    /**
     * Constructor
     * 
     * @param string $apiKey The expected API key for authentication
     */
    public function __construct($apiKey)
    {
        $this->apiKey = $apiKey;
    }

    /**
     * When this method is called, the backend must check if authentication was
     * successful.
     *
     * The returned value must be one of the following:
     * 
     * [true, "principals/username"] - authentication was successful, and a principal url is returned.
     * [false, "reason for failure"] - authentication failed, reason is optional
     * [null, null] - The backend cannot determine. The next backend will be queried.
     *
     * @param RequestInterface $request
     * @param ResponseInterface $response
     * @return array
     */
    public function check(RequestInterface $request, ResponseInterface $response)
    {
        // Get user from X-Forwarded-User header (required)
        $xForwardedUser = $request->getHeader('X-Forwarded-User');
        if (!$xForwardedUser) {
            return [false, 'X-Forwarded-User header is required'];
        }
        
        // API key is required
        $apiKeyHeader = $request->getHeader('X-Api-Key');
        if (!$apiKeyHeader) {
            return [false, 'X-Api-Key header is required'];
        }
        
        // Validate API key
        if ($apiKeyHeader !== $this->apiKey) {
            return [false, 'Invalid API key'];
        }
        
        // Authentication successful
        return [true, 'principals/' . $xForwardedUser];
    }

    /**
     * This method is called when a user could not be authenticated.
     *
     * This gives us a chance to set up authentication challenges (for example HTTP auth).
     *
     * @param RequestInterface $request
     * @param ResponseInterface $response
     * @return void
     */
    public function challenge(RequestInterface $request, ResponseInterface $response)
    {
        // We don't use HTTP Basic/Digest auth, so no challenge needed
        // The error message from check() will be returned
    }
}
