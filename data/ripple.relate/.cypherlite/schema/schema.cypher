CREATE CONSTRAINT `alert_id` FOR (n:`Alert`) REQUIRE (n.`id`) IS UNIQUE;
CREATE CONSTRAINT `customer_id` FOR (n:`Customer`) REQUIRE (n.`id`) IS UNIQUE;
CREATE CONSTRAINT `port_code` FOR (n:`Port`) REQUIRE (n.`code`) IS UNIQUE;
CREATE CONSTRAINT `product_sku` FOR (n:`Product`) REQUIRE (n.`sku`) IS UNIQUE;
CREATE CONSTRAINT `route_id` FOR (n:`Route`) REQUIRE (n.`id`) IS UNIQUE;
CREATE CONSTRAINT `shipment_id` FOR (n:`Shipment`) REQUIRE (n.`id`) IS UNIQUE;
CREATE CONSTRAINT `vessel_imo` FOR (n:`Vessel`) REQUIRE (n.`imo`) IS UNIQUE;
