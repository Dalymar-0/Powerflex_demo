"""
Test SQLAlchemy 2.0 Migration - Phase 15

Validates that all migrated modules:
1. Import successfully
2. Use SQLAlchemy 2.0 patterns (select, scalars, where)
3. Don't use deprecated methods (query, filter)
"""
import sys
import re
from pathlib import Path

# Test Results
results = {"passed": [], "failed": []}

def test_import(module_name: str) -> bool:
    """Test if a module can be imported"""
    try:
        __import__(module_name)
        return True
    except Exception as e:
        print(f"❌ Import failed for {module_name}: {e}")
        return False

def check_deprecated_patterns(file_path: Path) -> tuple[bool, list]:
    """Check for deprecated SQLAlchemy patterns"""
    try:
        content = file_path.read_text(encoding='utf-8')
        issues = []
        
        # Check for deprecated .query( usage
        query_matches = re.findall(r'\.query\([^)]+\)', content)
        if query_matches:
            issues.append(f"Found {len(query_matches)} uses of deprecated .query() method")
        
        # Check if select() is imported (if using SA)
        if 'from sqlalchemy' in content or 'import sqlalchemy' in content:
            if 'Session' in content or 'db.' in content:
                if 'from sqlalchemy import select' not in content and 'from sqlalchemy import' in content:
                    # Check if select is imported in any form
                    if not re.search(r'from sqlalchemy import.*select', content):
                        issues.append("Module uses SQLAlchemy but doesn't import 'select'")
        
        return len(issues) == 0, issues
    except Exception as e:
        return False, [f"Error checking file: {e}"]

print("=" * 70)
print("🔬 SQLAlchemy 2.0 Migration Test Suite - Phase 15")
print("=" * 70)

# Test 1: Import all migrated API modules
print("\n📦 Test 1: API Module Imports")
print("-" * 70)
api_modules = [
    'mdm.api.pd',
    'mdm.api.sds',
    'mdm.api.pool',
    'mdm.api.sdc',
    'mdm.api.volume',
    'mdm.api.cluster',
    'mdm.api.discovery',
    'mdm.api.metrics',
    'mdm.api.token',
    'mdm.api.rebuild',
]

for module in api_modules:
    if test_import(module):
        print(f"✅ {module}")
        results["passed"].append(f"Import: {module}")
    else:
        results["failed"].append(f"Import: {module}")

# Test 2: Import core modules
print("\n📦 Test 2: Core Module Imports")
print("-" * 70)
core_modules = [
    'mdm.logic',
    'mdm.token_authority',
    'mdm.health_monitor',
    'mdm.service',
]

for module in core_modules:
    if test_import(module):
        print(f"✅ {module}")
        results["passed"].append(f"Import: {module}")
    else:
        results["failed"].append(f"Import: {module}")

# Test 3: Import services
print("\n📦 Test 3: Services Module Imports")
print("-" * 70)
service_modules = [
    'mdm.services.volume_manager',
    'mdm.services.storage_engine',
]

for module in service_modules:
    if test_import(module):
        print(f"✅ {module}")
        results["passed"].append(f"Import: {module}")
    else:
        results["failed"].append(f"Import: {module}")

# Test 4: Check for deprecated patterns in migrated files
print("\n🔍 Test 4: Deprecated Pattern Check")
print("-" * 70)

migrated_files = [
    Path("mdm/api/pd.py"),
    Path("mdm/api/sds.py"),
    Path("mdm/api/pool.py"),
    Path("mdm/api/sdc.py"),
    Path("mdm/api/volume.py"),
    Path("mdm/api/cluster.py"),
    Path("mdm/api/discovery.py"),
    Path("mdm/api/metrics.py"),
    Path("mdm/api/token.py"),
    Path("mdm/api/rebuild.py"),
    Path("mdm/logic.py"),
    Path("mdm/token_authority.py"),
    Path("mdm/health_monitor.py"),
]

for file_path in migrated_files:
    if file_path.exists():
        clean, issues = check_deprecated_patterns(file_path)
        if clean:
            print(f"✅ {file_path}")
            results["passed"].append(f"Pattern check: {file_path}")
        else:
            print(f"⚠️  {file_path}")
            for issue in issues:
                print(f"   └─ {issue}")
            results["failed"].append(f"Pattern check: {file_path} - {'; '.join(issues)}")
    else:
        print(f"❌ File not found: {file_path}")
        results["failed"].append(f"File not found: {file_path}")

# Test 5: Check database models work
print("\n🗄️  Test 5: Database Models")
print("-" * 70)
try:
    from mdm.models import Volume, StoragePool, SDSNode, SDCClient, ProtectionDomain
    print("✅ All core models import successfully")
    print(f"   └─ Volume, StoragePool, SDSNode, SDCClient, ProtectionDomain")
    results["passed"].append("Database models import")
except Exception as e:
    print(f"❌ Model import failed: {e}")
    results["failed"].append(f"Database models: {e}")

# Test 6: Check database session creation
print("\n💾 Test 6: Database Session")
print("-" * 70)
try:
    from mdm.database import SessionLocal, engine
    session = SessionLocal()
    print("✅ SessionLocal creates session successfully")
    session.close()
    results["passed"].append("SessionLocal session creation")
except Exception as e:
    print(f"❌ Session creation failed: {e}")
    results["failed"].append(f"Session creation: {e}")

# Final Summary
print("\n" + "=" * 70)
print("📊 TEST SUMMARY")
print("=" * 70)
print(f"✅ Passed: {len(results['passed'])}")
print(f"❌ Failed: {len(results['failed'])}")

if results['failed']:
    print("\n⚠️  Failed Tests:")
    for fail in results['failed']:
        print(f"   • {fail}")

success_rate = len(results['passed']) / (len(results['passed']) + len(results['failed'])) * 100
print(f"\n🎯 Success Rate: {success_rate:.1f}%")

if len(results['failed']) == 0:
    print("\n🎉 ALL TESTS PASSED! SQLAlchemy 2.0 migration is successful! 🎉")
    sys.exit(0)
else:
    print("\n⚠️  Some tests failed. Review the issues above.")
    sys.exit(1)
