# API reference

The public functions, classes and methods of every module with their signatures, as of this
release. Tests and migrations are not listed.

## `server/src/app.ts`

- `function createApp()`

## `server/src/controllers/bookingController.ts`

- `async function create(req: Request, res: Response): Promise<void>`
- `async function cancel(req: Request<{ id: string }>, res: Response): Promise<void>`
- `async function checkIn(req: Request<{ id: string }>, res: Response): Promise<void>`
- `async function listMine(req: Request, res: Response): Promise<void>`
- `async function listForRoom(req: Request<{ roomId: string }>, res: Response): Promise<void>`

## `server/src/controllers/roomController.ts`

- `async function list(_req: Request, res: Response): Promise<void>`
- `async function get(req: Request<{ roomId: string }>, res: Response): Promise<void>`
- `async function availability(req: Request<{ roomId: string }>, res: Response): Promise<void>`
- `async function update(req: Request<{ roomId: string }>, res: Response): Promise<void>`
- `async function archive(req: Request<{ roomId: string }>, res: Response): Promise<void>`

## `server/src/domain/types.ts`

- `const SLOT_MINUTES`
- `const OPENING_HOUR`
- `const CLOSING_HOUR`
- `type Role`
- `interface Actor`
- `interface Room`
- `type BookingStatus`
- `interface Booking`
- `interface Slot`
- `interface Range`

## `server/src/lib/audit.ts`

- `interface AuditEvent`
- `function record(event: AuditEvent): Promise<void>`

## `server/src/lib/db.ts`

- `class Sql`
- `function sql(strings: TemplateStringsArray, ...values: unknown[]): Sql`
- `const emptySql`
- `function compile(fragment: Sql)`
- `async function query<T>(fragment: Sql): Promise<T[]>`
- `async function queryOne<T>(fragment: Sql): Promise<T | undefined>`

## `server/src/lib/errors.ts`

- `type ErrorCode`
- `class AppError extends Error`
- `const notFound`
- `const conflict`
- `const forbidden`
- `const unprocessable`

## `server/src/lib/http.ts`

- `function sendErrorResponse(res: Response, error: AppError): void`
- `function sendResult<T>(res: Response, result: Result<T, AppError>, status = 200): void`
- `function errorHandler(error: unknown, req: Request, res: Response, _next: NextFunction)`

## `server/src/lib/logger.ts`

- `const logger`

## `server/src/lib/notifier.ts`

- `async function bookingConfirmed(booking: Booking): Promise<void>`

## `server/src/lib/result.ts`

- `type Ok<T>`
- `type Err<E>`
- `type Result<T, E = AppError>`
- `function ok<T>(value: T): Ok<T>`
- `function err<E>(error: E): Err<E>`
- `function map<T, U, E>(result: Result<T, E>, fn: (value: T) => U): Result<U, E>`

## `server/src/lib/time.ts`

- `type Instant`
- `const END_OF_TIME: Instant`
- `function now(): Instant`
- `function toInstant(value: Date | string): Instant`
- `function addMinutes(at: Instant, minutes: number): Instant`
- `function minutesBetween(start: Instant, end: Instant): number`
- `function isBefore(a: Instant, b: Instant): boolean`
- `function isAfter(a: Instant, b: Instant): boolean`
- `function startOfUtcDay(at: Instant): Instant`
- `function utcDay(day: string): Instant`
- `function utcDayOfWeek(at: Instant): number`
- `function isOnSlotBoundary(at: Instant, slotMinutes: number): boolean`

## `server/src/middleware/auth.ts`

- `const SESSION_COOKIE`
- `async function requireAuth(req: Request, res: Response, next: NextFunction): Promise<void>`
- `function requireRole(...roles: Role[])`
- `function actorOf(req: Request): Actor`

## `server/src/middleware/validate.ts`

- `function validateBody(schema: ZodTypeAny)`
- `function validateQuery(schema: ZodTypeAny)`

## `server/src/repositories/bookingRepository.ts`

- `async function findById(id: string): Promise<Booking | undefined>`
- `const DEFAULT_PAGE_SIZE`
- `interface Page`
- `async function listForRoom( roomId: string, range: Range, page: Page = { limit: DEFAULT_PAGE_SIZE, offset: 0 }, ): Promise<Booking[]>`
- `async function countForRoom(roomId: string, range: Range): Promise<number>`
- `async function listForUser(userId: string, range: Partial<Range>): Promise<Booking[]>`
- `async function findOverlapping(roomId: string, slot: Slot): Promise<Booking[]>`
- `interface NewBooking`
- `async function insert(booking: NewBooking): Promise<Booking>`
- `async function markCancelled(id: string, at: Instant): Promise<Booking | undefined>`
- `async function markCheckedIn(id: string): Promise<Booking | undefined>`

## `server/src/repositories/eventRepository.ts`

- `async function insertAudit(event: AuditEvent): Promise<void>`
- `async function enqueueOutbox(topic: string, payload: Record<string, unknown>): Promise<void>`

## `server/src/repositories/roomRepository.ts`

- `interface RoomFilters`
- `async function list(filters: RoomFilters): Promise<Room[]>`
- `async function findById(id: string): Promise<Room | undefined>`
- `interface RoomPatch`
- `async function update(id: string, patch: RoomPatch): Promise<Room | undefined>`

## `server/src/repositories/userRepository.ts`

- `async function findActorBySession(token: string): Promise<Actor | undefined>`

## `server/src/routes.ts`

- `const router`

## `server/src/schemas/booking.ts`

- `const instant`
- `const createBookingBody`
- `type CreateBookingInput`
- `const rangeQuery`
- `type RangeQuery`
- `const roomBookingsQuery`
- `type RoomBookingsQuery`

## `server/src/schemas/room.ts`

- `const listRoomsQuery`
- `type ListRoomsQuery`
- `const updateRoomBody`
- `type UpdateRoomInput`
- `const availabilityQuery`
- `type AvailabilityQuery`

## `server/src/services/availabilityService.ts`

- `async function getFreeSlots(roomId: string, day: string): Promise<Result<Slot[]>>`

## `server/src/services/bookingService.ts`

- `async function createBooking( actor: Actor, input: CreateBookingInput, ): Promise<Result<Booking>>`
- `async function cancelBooking(actor: Actor, id: string): Promise<Result<Booking>>`
- `async function checkIn(actor: Actor, id: string): Promise<Result<Booking>>`
- `async function listMyBookings(actor: Actor, range: RangeQuery): Promise<Result<Booking[]>>`
- `interface BookingPage`
- `async function listRoomBookings( roomId: string, query: RoomBookingsQuery, ): Promise<Result<BookingPage>>`

## `server/src/services/roomService.ts`

- `async function listRooms(filters: ListRoomsQuery): Promise<Result<Room[]>>`
- `async function getRoom(id: string): Promise<Result<Room>>`
- `async function updateRoom( actor: Actor, id: string, patch: UpdateRoomInput, ): Promise<Result<Room>>`
- `async function archiveRoom(actor: Actor, id: string): Promise<Result<Room>>`

## `web/src/App.tsx`

- `function App()`

## `web/src/api/client.ts`

- `class ApiError extends Error`
- `const apiClient`

## `web/src/api/queryKeys.ts`

- `interface RoomFilters`
- `const queryKeys`

## `web/src/api/useBookings.ts`

- `function useMyBookings()`
- `interface NewBooking`
- `function useCreateBooking()`
- `function useCancelBooking()`

## `web/src/api/useRoomSchedule.ts`

- `function useRoomSchedule(roomId: string, from: string)`

## `web/src/api/useRooms.ts`

- `function useRooms(filters: RoomFilters = {})`
- `function useRoom(roomId: string)`
- `function useAvailability(roomId: string, day: string)`

## `web/src/components/AvailabilityGrid.tsx`

- `function AvailabilityGrid({ roomId, day }: Props)`

## `web/src/components/BookingCard.tsx`

- `function BookingCard({ booking, roomName, onCancel, cancelling = false }: Props)`

## `web/src/components/BookingList.tsx`

- `function groupByDay(bookings: Booking[]): DayGroup[]`
- `function BookingList({ bookings, rooms, onCancel, cancellingId }: Props)`

## `web/src/components/CheckInButton.tsx`

- `function CheckInButton({ booking }: Props)`

## `web/src/components/ErrorBanner.tsx`

- `function ErrorBanner({ error }: { error: unknown })`

## `web/src/components/RoomPicker.tsx`

- `function RoomPicker({ rooms }: Props)`

## `web/src/components/RoomSchedule.tsx`

- `function RoomSchedule({ roomId }: Props)`

## `web/src/lib/flags.ts`

- `type FlagName`
- `const flags`

## `web/src/lib/format.ts`

- `function formatTime(iso: string): string`
- `function formatDay(iso: string): string`
- `function formatTimeRange(startIso: string, endIso: string): string`
- `function formatPrice(cents: number, currency: string): string`
- `function toDayParam(iso: string): string`
- `function isCheckInOpen(startIso: string, now: Date = new Date()): boolean`
- `function isInFuture(iso: string, now: Date = new Date()): boolean`

## `web/src/pages/MyBookingsPage.tsx`

- `function MyBookingsPage()`

## `web/src/pages/RoomPage.tsx`

- `function RoomPage()`

## `web/src/pages/RoomsPage.tsx`

- `function RoomsPage()`

## `web/src/types.ts`

- `interface Room`
- `type BookingStatus`
- `interface Booking`
- `interface Slot`
