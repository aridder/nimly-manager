"""Load pure integration-domain modules without a Home Assistant runtime."""

import sys
from pathlib import Path
from types import ModuleType

PACKAGE_NAME = "custom_components.nimly_manager"
PACKAGE_PATH = Path(__file__).parents[1] / "custom_components" / "nimly_manager"

package = ModuleType(PACKAGE_NAME)
package.__package__ = PACKAGE_NAME
package.__path__ = [str(PACKAGE_PATH)]
sys.modules[PACKAGE_NAME] = package
