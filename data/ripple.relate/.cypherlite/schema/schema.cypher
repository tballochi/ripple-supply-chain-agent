CREATE VECTOR INDEX `alert_embedding` FOR (n:`Alert`) ON (n.`embedding`) OPTIONS {indexConfig: {`vector.default_search_expansion_factor`: 3.0,`vector.dimensions`: 384,`vector.hnsw.ef_construction`: 100,`vector.hnsw.m`: 16,`vector.quantization.type`: 'BINARY',`vector.similarity_function`: 'COSINE'}};
CREATE FULLTEXT INDEX `alert_text` FOR (n:`Alert`) ON EACH [n.`text`] OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard-no-stop-words',`fulltext.eventually_consistent`: false}};
CREATE CONSTRAINT `alert_id` FOR (n:`Alert`) REQUIRE (n.`id`) IS UNIQUE;
CREATE CONSTRAINT `customer_id` FOR (n:`Customer`) REQUIRE (n.`id`) IS UNIQUE;
CREATE CONSTRAINT `port_code` FOR (n:`Port`) REQUIRE (n.`code`) IS UNIQUE;
CREATE CONSTRAINT `product_sku` FOR (n:`Product`) REQUIRE (n.`sku`) IS UNIQUE;
CREATE CONSTRAINT `route_id` FOR (n:`Route`) REQUIRE (n.`id`) IS UNIQUE;
CREATE CONSTRAINT `shipment_id` FOR (n:`Shipment`) REQUIRE (n.`id`) IS UNIQUE;
CREATE CONSTRAINT `vessel_imo` FOR (n:`Vessel`) REQUIRE (n.`imo`) IS UNIQUE;
