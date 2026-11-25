<?php

namespace Calendars\SabreDav\Tests;

use Calendars\SabreDav\AnswerOnlyChange;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;
use Sabre\VObject\Reader;

/**
 * Each case is a folder with the stored event and the new event. The
 * name of the parent folder gives the expected result.
 */
final class AnswerOnlyChangeTest extends TestCase
{
    private const FIXTURES = __DIR__ . '/fixtures/AnswerOnlyChange';

    /**
     * @return iterable<string, array{string, bool}>
     */
    public static function cases(): iterable
    {
        foreach (['answer-only' => true, 'not-answer-only' => false] as $group => $expected) {
            foreach (glob(self::FIXTURES . "/$group/*", GLOB_ONLYDIR) as $folder) {
                yield "$group/" . basename($folder) => [$folder, $expected];
            }
        }
    }

    #[DataProvider('cases')]
    public function testIsAnswerOnly(string $folder, bool $expected): void
    {
        $stored = Reader::read(file_get_contents("$folder/stored.ics"));
        $new = Reader::read(file_get_contents("$folder/new.ics"));

        $this->assertSame($expected, (new AnswerOnlyChange())->isAnswerOnly($new, $stored));
    }
}
