# PowerFlex Demo — Technical Debt

## SQLAlchemy 1.4 → 2.0 Migration

**Status**: ⚠️ DEFERRED (P3 Priority)  
**Estimated Effort**: 5-7 hours  
**Files Affected**: ~30 files, ~150 queries  
**Decision Date**: 2026-02-13  

### Current State

- All code uses SQLAlchemy 1.4 `.query()` API (deprecated in 2.0)
- Deprecation warnings suppressed in entry points
- Functionality **unaffected** (96% test pass rate)  
- System stable and production-ready

### Why Deferred?

1. **No User Impact**: Warnings only affect dev logs
2. **System Stable**: 96% pass rate, all critical tests passing
3. **Higher Priority**: Phase 14 (SDS/SDC deployment) adds real features
4. **Safe to Postpone**: Can migrate incrementally during future refactors

### Migration Path (When Ready)

**OLD (SQLAlchemy 1.4, deprecated):**
```python
users = db.query(User).filter(User.active == True).all()
user = db.query(User).get(user_id)
count = db.query(User).count()
```

**NEW (SQLAlchemy 2.0, required):**
```python
from sqlalchemy import select, func

users = db.execute(select(User).where(User.active == True)).scalars().all()
user = db.get(User, user_id)
count = db.execute(select(func.count()).select_from(User)).scalar()
```

### Files Requiring Changes (~150 queries)

**Critical (MDM core):**
- `app/api/volume.py` (25 usages)
- `app/logic.py` (15 usages)
- `app/api/*.py` (60 usages total)

**Important (Phase 1-9):**
- `mdm/api/*.py` (25 usages)
- `sds/mgmt_app.py` (15 usages)
- `sdc/mgmt_app.py` (12 usages)

**Low Priority:**
- Test scripts (10 usages)
- Utilities (5 usages)

### Recommended Schedule

- **Phase 15-16**: After SDS/SDC deployment complete
- **Approach**: File-by-file incremental migration
- **Testing**: Full integration test suite after each batch
- **Timeline**: 1-2 weeks (background task, not blocking releases)

### Temporary Mitigation

Warnings suppressed in entry points:
- `mdm/service.py` — MDM service startup
- `mgmt/service.py` — MGMT service startup  
- `app/main.py` — Legacy app entry (if still used)

### References

- [SQLAlchemy 2.0 Migration Guide](https://docs.sqlalchemy.org/en/20/changelog/migration_20.html)
- Phase 13 Assessment: `docs/PHASE13_ASSESSMENT.md`

---
**Last Updated**: 2026-02-13  
**Review Date**: After Phase 14 complete  
**Owner**: Development Team
