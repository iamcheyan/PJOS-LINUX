// SPDX-License-Identifier: GPL-2.0
/* Start the H700 USB host controllers that the boot device tree holds back.
 *
 * The vendor kernel brings up each EHCI/OHCI host controller in turn before it
 * starts init: about 30 ms per EHCI and 70 ms per OHCI. BaseOS boot files mark
 * every host controller except EHCI 2 with status "late", so the kernel skips
 * them, and rcS loads this module beside the rest of startup to create them.
 * EHCI 2 stays in the device tree as "okay": the OTG port does not enumerate
 * as a device without it.
 *
 * Nothing here is vendor-private. A node is touched only if its status is
 * exactly "late"; on boot files that never held it back this module does
 * nothing. Uses exported device-tree and platform-bus calls only.
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/string.h>
#include <linux/slab.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>

#define HELD_BACK "late"

static const char *const controllers[] = {
	"allwinner,sunxi-ehci1", "allwinner,sunxi-ohci1",
	"allwinner,sunxi-ohci2",
	"allwinner,sunxi-ehci3", "allwinner,sunxi-ohci3",
};

static int __init h700_late_usb_init(void)
{
	unsigned int i, started = 0, failed = 0;

	for (i = 0; i < ARRAY_SIZE(controllers); i++) {
		struct device_node *node, *bus;
		struct platform_device *bus_device, *created;
		struct property *status;
		char *available;
		int length;

		node = of_find_compatible_node(NULL, NULL, controllers[i]);
		if (!node)
			continue;
		status = of_find_property(node, "status", &length);
		if (!status || length != sizeof(HELD_BACK) ||
		    memcmp(status->value, HELD_BACK, sizeof(HELD_BACK))) {
			of_node_put(node);
			continue;
		}
		/* The platform bus refuses a node that is not available. Property
		 * values still point into the boot-time device-tree blob, which is
		 * mapped read-only, so give the property a value of its own. It is
		 * never freed: the node keeps it for as long as the system runs.
		 */
		available = kstrdup("okay", GFP_KERNEL);
		if (!available) {
			of_node_put(node);
			return -ENOMEM;
		}
		status->value = available;
		status->length = sizeof("okay");
		bus = of_get_parent(node);
		bus_device = bus ? of_find_device_by_node(bus) : NULL;
		created = of_platform_device_create(node, NULL,
						    bus_device ? &bus_device->dev : NULL);
		if (created) {
			started++;
		} else {
			failed++;
			pr_err("h700_late_usb: could not create %s\n", controllers[i]);
		}
		if (bus_device)
			put_device(&bus_device->dev);
		of_node_put(bus);
		of_node_put(node);
	}
	pr_info("h700_late_usb: started %u held-back host controllers, %u failed\n",
		started, failed);
	return 0;
}
module_init(h700_late_usb_init);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Start H700 USB host controllers held back by the boot device tree");
