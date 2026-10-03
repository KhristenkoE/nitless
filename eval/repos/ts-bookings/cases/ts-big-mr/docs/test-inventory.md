# Test inventory

The automated tests by file, for the release audit trail; a parameterized test is listed once,
with its placeholders. Regenerate it when tests change. 48 tests are listed.

## `server/test/auth.test.ts` (6)

- responds with 401 without a lookup when %s
- responds with 401 when the session is unknown or expired
- attaches the actor of a valid session and continues
- responds with 403 when no actor is attached
- returns the authenticated actor
- throws when used on a route without requireAuth

## `server/test/availabilityService.test.ts` (4)

- returns NOT_FOUND for an %s room
- lists every 30-minute slot between opening and closing on a free day
- at %s omits started slots and starts at %s (%i left)
- returns no slots once the room has closed

## `server/test/bookingService.test.ts` (6)

- creates a booking in a free slot
- rejects overlapping bookings
- enforces the room duration limit
- rejects slots that are not aligned
- does not let members cancel bookings of others
- is idempotent for already cancelled bookings

## `server/test/http.test.ts` (5)

- includes the error details in the envelope
- wraps a successful value in a data envelope
- uses the given status for successful results
- sends thrown AppErrors as they are, without logging
- logs unexpected errors and hides them behind a generic 500

## `server/test/roomSchema.test.ts` (5)

- accepts %o
- trims the room name
- rejects %o as having nothing to update
- accepts a calendar day
- rejects %j

## `server/test/roomService.test.ts` (3)

- records which fields an update touched
- records archiving together with the cancelled bookings
- does not record anything for unknown rooms

## `server/test/time.test.ts` (5)

- normalises instants to UTC ISO strings
- adds minutes across day boundaries
- counts whole minutes between instants
- computes UTC days
- checks slot boundaries

## `server/test/validate.test.ts` (3)

- replaces the body with the parsed value and continues
- stores the parsed query %o in res.locals as %o
- responds with 400 for an invalid query string

## `web/src/api/client.test.ts` (4)

- sends GET requests with the defined query parameters and unwraps the data
- sends a body as JSON
- omits the body and content type when there is nothing to send
- turns an error envelope into an ApiError

## `web/src/components/BookingList.test.tsx` (3)

- groups bookings by UTC start day in order
- renders one section per day
- shows an empty state

## `web/src/lib/flags.test.ts` (1)

- with VITE_FLAGS=%j enables %j

## `web/src/lib/format.test.ts` (3)

- formats a time range in UTC
- extracts the UTC day parameter
- compares against an injectable now
