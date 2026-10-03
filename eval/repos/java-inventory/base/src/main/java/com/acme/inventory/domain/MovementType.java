package com.acme.inventory.domain;

/**
 * Kind of stock movement and how it affects a stock level.
 *
 * <p>{@link com.acme.inventory.service.StockLedger#record} multiplies the recorded quantity by
 * {@link #onHandSign()} and {@link #reservedSign()}. The quantity of an {@link #ADJUSTMENT} is a
 * signed delta chosen by the caller; for every other type it is the (positive) amount moved and
 * the direction comes from the type.
 */
public enum MovementType {
    RECEIPT(1, 0),
    SHIPMENT(-1, 0),
    ADJUSTMENT(1, 0),
    RESERVE(0, 1),
    RELEASE(0, -1),
    FULFILL(-1, -1);

    private final int onHandSign;
    private final int reservedSign;

    MovementType(int onHandSign, int reservedSign) {
        this.onHandSign = onHandSign;
        this.reservedSign = reservedSign;
    }

    public int onHandSign() {
        return onHandSign;
    }

    public int reservedSign() {
        return reservedSign;
    }
}
