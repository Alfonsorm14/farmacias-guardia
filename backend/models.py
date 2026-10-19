"""Modelos de base de datos para farmacias de guardia (SQLAlchemy 2.0)."""
from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UTCDateTime(TypeDecorator):
    """DateTime type that stores UTC in DB and returns timezone-aware UTC datetime."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if not isinstance(value, datetime.datetime):
                raise TypeError("Expected datetime object")
            if value.tzinfo is None:
                value = value.replace(tzinfo=datetime.timezone.utc)
            else:
                value = value.astimezone(datetime.timezone.utc)
            if dialect.name == "sqlite":
                return value.replace(tzinfo=None)
            return value
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=datetime.timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    publisher: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    license: Mapped[str] = mapped_column(String(255), nullable=False)
    retrieved_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False)

    pharmacies: Mapped[list["Pharmacy"]] = relationship(
        "Pharmacy", back_populates="source", cascade="all, delete-orphan"
    )
    shifts: Mapped[list["Shift"]] = relationship(
        "Shift", back_populates="source", cascade="all, delete-orphan"
    )


class Pharmacy(Base):
    __tablename__ = "pharmacies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    region: Mapped[str] = mapped_column(String(10), nullable=False)
    holder: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    locality: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    duty_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sources.source_id"), nullable=False
    )
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    geo_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    geo_precision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    geo_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    zones: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    source: Mapped[Source] = relationship("Source", back_populates="pharmacies")
    shifts: Mapped[list["Shift"]] = relationship(
        "Shift", back_populates="pharmacy", cascade="all, delete-orphan"
    )


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pharmacy_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("pharmacies.id"), nullable=False
    )
    zone: Mapped[str] = mapped_column(String(255), nullable=False)
    start_utc: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False)
    end_utc: Mapped[datetime.datetime] = mapped_column(UTCDateTime, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_label: Mapped[str] = mapped_column(String(255), nullable=False)
    times_exact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sources.source_id"), nullable=False
    )

    pharmacy: Mapped[Pharmacy] = relationship("Pharmacy", back_populates="shifts")
    source: Mapped[Source] = relationship("Source", back_populates="shifts")

    __table_args__ = (
        UniqueConstraint(
            "pharmacy_id",
            "zone",
            "start_utc",
            "kind",
            name="uq_shifts_pharmacy_zone_start_kind",
        ),
        Index("ix_shifts_start_end", "start_utc", "end_utc"),
        Index("ix_shifts_pharmacy_id", "pharmacy_id"),
    )


class GeocodeCache(Base):
    __tablename__ = "geocode_cache"

    query: Mapped[str] = mapped_column(String(500), primary_key=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    precision: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.timezone.utc),
    )
