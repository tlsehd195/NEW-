---
type: entity
title: notifications
tags:
  - module
  - notifications
created: '2026-09-24T10:17:23.020Z'
---
## 역할
스케줄된 리포트의 아웃바운드 알림 전송(Session 38). 현재 구현된 채널은 Discord webhook 하나(`notifications.discord_webhook`).

## 핵심 인터페이스/클래스
- 별도 Repository/Protocol 없음 — 가장 작은 모듈(2 파일).

## 경계
알림 전송만 담당 — 리포트 생성 로직은 포함하지 않음.
