-- Table structure for table `asset`
--

DROP TABLE IF EXISTS `asset`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `asset` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `asset_code` varchar(255) DEFAULT NULL COMMENT '资产编码',
  `asset_name` varchar(255) DEFAULT NULL COMMENT '资产名称',
  `asset_type` varchar(255) DEFAULT NULL COMMENT '资产类型',
  `asset_specification` varchar(255) DEFAULT NULL COMMENT '规格型号',
  `asset_unit` varchar(255) DEFAULT NULL COMMENT '单位',
  `asset_quantity` decimal(10,2) DEFAULT NULL COMMENT '数量',
  `asset_price` decimal(15,4) DEFAULT NULL COMMENT '单价',
  `asset_amount` decimal(15,4) DEFAULT NULL COMMENT '总金额',
  `asset_status` varchar(50) DEFAULT NULL COMMENT '资产状态：idle-闲置, in_use-使用中, maintenance-维修中, scrapped-已报废',
  `asset_location` varchar(255) DEFAULT NULL COMMENT '存放位置',
  `responsible_person` varchar(255) DEFAULT NULL COMMENT '责任人',
  `purchase_date` varchar(255) DEFAULT NULL COMMENT '购入日期',
  `expected_life` int(11) DEFAULT NULL COMMENT '预计使用年限（年）',
  `depreciation_method` varchar(50) DEFAULT NULL COMMENT '折旧方法：straight_line-直线法, double_declining-双倍余额递减法',
  `salvage_value` decimal(15,4) DEFAULT NULL COMMENT '残值',
  `remark` varchar(500) DEFAULT NULL COMMENT '备注',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `asset_code` (`asset_code`)
) ENGINE=MyISAM AUTO_INCREMENT=31 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `brand`
--

DROP TABLE IF EXISTS `brand`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `brand` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(255) DEFAULT NULL COMMENT '名称',
  `letter` varchar(255) DEFAULT NULL COMMENT '字母',
  `status` varchar(255) DEFAULT NULL COMMENT '状态：active-启用, inactive-禁用',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=11 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `category`
--

DROP TABLE IF EXISTS `category`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `category` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(255) DEFAULT NULL COMMENT '名称',
  `parent_id` int(11) DEFAULT NULL COMMENT '父ID',
  `status` varchar(255) DEFAULT NULL COMMENT '状态：active-启用, inactive-禁用',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=16 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `component`
--

DROP TABLE IF EXISTS `component`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `component` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `code` varchar(255) DEFAULT NULL COMMENT '组件编码',
  `name` varchar(255) DEFAULT NULL COMMENT '组件名称',
  `description` varchar(500) DEFAULT NULL COMMENT '组件描述',
  `parent_id` int(11) DEFAULT NULL COMMENT '父组件ID',
  `type` varchar(50) DEFAULT NULL COMMENT '组件类型: menu/button/api',
  `path` varchar(500) DEFAULT NULL COMMENT '访问路径',
  `component` varchar(500) DEFAULT NULL COMMENT '组件路径',
  `icon` varchar(100) DEFAULT NULL COMMENT '图标',
  `sort` int(11) DEFAULT NULL COMMENT '排序',
  `level` int(11) DEFAULT NULL COMMENT '菜单层级',
  `full_path` varchar(2000) DEFAULT NULL COMMENT '树路径，逗号分隔',
  `status` varchar(50) DEFAULT NULL COMMENT '状态：active-启用, inactive-禁用',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=MyISAM AUTO_INCREMENT=26 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `customer`
--

DROP TABLE IF EXISTS `customer`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `customer` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `customer_name` varchar(255) DEFAULT NULL COMMENT '客户名称',
  `customer_type` varchar(255) DEFAULT NULL COMMENT '客户类型',
  `contact_person` varchar(255) DEFAULT NULL COMMENT '联系人',
  `contact_phone` varchar(255) DEFAULT NULL COMMENT '联系电话',
  `customer_email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `customer_address` varchar(255) DEFAULT NULL COMMENT '地址',
  `status` varchar(255) DEFAULT NULL COMMENT '状态：active-启用, inactive-禁用',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=101 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `inventory`
--

DROP TABLE IF EXISTS `inventory`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `inventory` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `product_code` varchar(255) DEFAULT NULL COMMENT '商品编码',
  `unit` varchar(255) DEFAULT NULL COMMENT '单位',
  `location` varchar(255) DEFAULT NULL COMMENT '库存位置',
  `current_quantity` decimal(15,4) DEFAULT NULL COMMENT '当前库存数量',
  `safety_stock` decimal(15,4) DEFAULT NULL COMMENT '安全库存数量',
  `warning_stock` decimal(15,4) DEFAULT NULL COMMENT '预警库存数量',
  `status` smallint(6) DEFAULT NULL COMMENT '状态：0-正常, 1-预警, 2-停用',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=51 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `inventory_record`
--

DROP TABLE IF EXISTS `inventory_record`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `inventory_record` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `product_code` varchar(255) DEFAULT NULL COMMENT '商品编码',
  `operation_type` varchar(50) DEFAULT NULL COMMENT '操作类型: stockin-入库, stockout-出库, transfer_in-调入, transfer_out-调出, check-盘点',
  `quantity` decimal(10,2) DEFAULT NULL COMMENT '操作数量',
  `unit` varchar(255) DEFAULT NULL COMMENT '单位',
  `location` varchar(255) DEFAULT NULL COMMENT '库存位置',
  `from_location` varchar(255) DEFAULT NULL COMMENT '调出位置',
  `to_location` varchar(255) DEFAULT NULL COMMENT '调入位置',
  `batch_number` varchar(255) DEFAULT NULL COMMENT '批次号',
  `production_date` varchar(255) DEFAULT NULL COMMENT '生产日期',
  `expiry_date` varchar(255) DEFAULT NULL COMMENT '过期日期',
  `actual_quantity` decimal(10,2) DEFAULT NULL COMMENT '实际数量',
  `system_quantity` decimal(10,2) DEFAULT NULL COMMENT '系统数量',
  `difference` decimal(10,2) DEFAULT NULL COMMENT '差异数量',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=501 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `order`
--

DROP TABLE IF EXISTS `order`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `order` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `sales_person` varchar(255) DEFAULT NULL COMMENT '销售员',
  `customer_name` varchar(255) DEFAULT NULL COMMENT '客户名称',
  `contact_phone` varchar(255) DEFAULT NULL COMMENT '客户电话',
  `customer_address` varchar(255) DEFAULT NULL COMMENT '客户地址',
  `total_amount` decimal(15,4) DEFAULT NULL COMMENT '总金额',
  `payment_method` varchar(255) DEFAULT NULL COMMENT '支付方式',
  `status` smallint(6) DEFAULT NULL COMMENT '状态:1-已创建 2-待审核 3-已驳回 4-已完成 5-已取消',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=301 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `order_detail`
--

DROP TABLE IF EXISTS `order_detail`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `order_detail` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `order_id` int(11) DEFAULT NULL COMMENT '订单ID',
  `line_number` int(11) DEFAULT NULL COMMENT '行号',
  `product_id` int(11) DEFAULT NULL COMMENT '产品ID',
  `product_code` varchar(255) DEFAULT NULL COMMENT '产品编码',
  `product_name` varchar(255) DEFAULT NULL COMMENT '产品名称',
  `product_category` varchar(255) DEFAULT NULL COMMENT '产品类别',
  `product_brand` varchar(255) DEFAULT NULL COMMENT '产品品牌',
  `product_specification` varchar(255) DEFAULT NULL COMMENT '产品规格',
  `product_unit` varchar(255) DEFAULT NULL COMMENT '产品单位',
  `price` decimal(15,4) DEFAULT NULL COMMENT '价格',
  `quantity` decimal(15,4) DEFAULT NULL COMMENT '数量',
  `amount` decimal(15,4) DEFAULT NULL COMMENT '商品总价',
  `tax_rate` decimal(15,4) DEFAULT NULL COMMENT '税率',
  `tax_amount` decimal(15,4) DEFAULT NULL COMMENT '税额',
  `total_amount` decimal(15,4) DEFAULT NULL COMMENT '含税总价',
  `remark` varchar(500) DEFAULT NULL COMMENT '备注',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=615 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `permission`
--

DROP TABLE IF EXISTS `permission`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `permission` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `code` varchar(80) DEFAULT NULL COMMENT '权限编码',
  `name` varchar(80) DEFAULT NULL COMMENT '权限名称',
  `type` varchar(50) DEFAULT NULL COMMENT '权限类型: menu/content/button/api',
  `parent_code` varchar(80) DEFAULT NULL COMMENT '父权限',
  `path` varchar(200) DEFAULT NULL COMMENT '访问路径',
  `sort` int(11) DEFAULT NULL COMMENT '排序',
  `level` int(11) DEFAULT NULL COMMENT '层级',
  `description` varchar(200) DEFAULT NULL COMMENT '权限描述',
  `status` varchar(50) DEFAULT NULL COMMENT '状态：active-启用, inactive-禁用',
  `created_by` varchar(80) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(80) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `product`
--

DROP TABLE IF EXISTS `product`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `product` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `product_code` varchar(255) DEFAULT NULL COMMENT '商品编码',
  `product_name` varchar(255) DEFAULT NULL COMMENT '商品名称',
  `product_brand` varchar(255) DEFAULT NULL COMMENT '商品品牌名称',
  `product_category` varchar(255) DEFAULT NULL COMMENT '商品分类名称',
  `supplier_name` varchar(255) DEFAULT NULL COMMENT '商品供应商名称',
  `specification` varchar(255) DEFAULT NULL COMMENT '商品规格',
  `description` varchar(255) DEFAULT NULL COMMENT '商品描述',
  `unit` varchar(255) DEFAULT NULL COMMENT '商品单位',
  `cost_price` decimal(15,4) DEFAULT NULL COMMENT '商品成本价格',
  `sale_price` decimal(15,4) DEFAULT NULL COMMENT '商品销售价格',
  `status` varchar(255) DEFAULT NULL COMMENT '商品状态：active-在售, inactive-下架',
  `remark` varchar(500) DEFAULT NULL COMMENT '备注',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `product_code` (`product_code`)
) ENGINE=MyISAM AUTO_INCREMENT=51 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `purchase`
--

DROP TABLE IF EXISTS `purchase`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `purchase` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `purchase_by` varchar(255) DEFAULT NULL COMMENT '采购人',
  `supplier_name` varchar(255) DEFAULT NULL COMMENT '供应商名称',
  `contact_person` varchar(255) DEFAULT NULL COMMENT '供应商联系人',
  `contact_phone` varchar(255) DEFAULT NULL COMMENT '供应商电话',
  `supplier_address` varchar(255) DEFAULT NULL COMMENT '供应商地址',
  `total_amount` decimal(15,4) DEFAULT NULL COMMENT '总金额',
  `payment_method` varchar(255) DEFAULT NULL COMMENT '支付方式',
  `status` smallint(6) DEFAULT NULL COMMENT '状态:1-已创建 2-待审核 3-已驳回 4-已完成 5-已取消',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注',
  `expected_delivery_date` varchar(255) DEFAULT NULL COMMENT '预计交货日期',
  `actual_delivery_date` varchar(255) DEFAULT NULL COMMENT '实际交货日期',
  `accept_by` varchar(255) DEFAULT NULL COMMENT '收货人',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=91 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `purchase_detail`
--

DROP TABLE IF EXISTS `purchase_detail`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `purchase_detail` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `purchase_id` int(11) DEFAULT NULL COMMENT '采购ID',
  `line_number` int(11) DEFAULT NULL COMMENT '行号',
  `product_code` varchar(255) DEFAULT NULL COMMENT '商品编码',
  `product_name` varchar(255) DEFAULT NULL COMMENT '商品名称',
  `product_category` varchar(255) DEFAULT NULL COMMENT '商品分类',
  `product_brand` varchar(255) DEFAULT NULL COMMENT '商品品牌',
  `product_specification` varchar(255) DEFAULT NULL COMMENT '商品规格',
  `product_unit` varchar(255) DEFAULT NULL COMMENT '商品单位',
  `product_price` decimal(15,4) DEFAULT NULL COMMENT '单价',
  `product_quantity` decimal(15,4) DEFAULT NULL COMMENT '数量',
  `product_amount` decimal(15,4) DEFAULT NULL COMMENT '总价（不包含税）=数量 × 单价',
  `tax_rate` decimal(15,4) DEFAULT NULL COMMENT '税率',
  `tax_amount` decimal(15,4) DEFAULT NULL COMMENT '税额=总价（不包含税）× 税率',
  `total_amount` decimal(15,4) DEFAULT NULL COMMENT '总金额=总价（不包含税）+税额',
  `remark` varchar(500) DEFAULT NULL COMMENT '备注',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `ix_purchase_detail_product_code` (`product_code`),
  KEY `ix_purchase_detail_purchase_id` (`purchase_id`),
  KEY `ix_purchase_detail_product_category` (`product_category`)
) ENGINE=MyISAM AUTO_INCREMENT=282 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `role`
--

DROP TABLE IF EXISTS `role`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `role` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `code` varchar(255) DEFAULT NULL COMMENT '角色编码',
  `name` varchar(255) DEFAULT NULL COMMENT '角色名称',
  `description` varchar(500) DEFAULT NULL COMMENT '角色描述',
  `status` varchar(50) DEFAULT NULL COMMENT '状态：active-启用, inactive-禁用',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=MyISAM AUTO_INCREMENT=6 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `role_permission`
--

DROP TABLE IF EXISTS `role_permission`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `role_permission` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `role_id` int(11) DEFAULT NULL COMMENT '角色ID',
  `permission_id` int(11) DEFAULT NULL COMMENT '权限ID',
  `permission` varchar(80) DEFAULT NULL COMMENT '权限：0-无, 1-只读, 2-读写',
  `created_by` varchar(80) DEFAULT NULL COMMENT '创建者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=39 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `supplier`
--

DROP TABLE IF EXISTS `supplier`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `supplier` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `supplier_name` varchar(50) DEFAULT NULL COMMENT '供应商名称',
  `supplier_type` varchar(255) DEFAULT NULL COMMENT '供应商类型',
  `contact_person` varchar(255) DEFAULT NULL COMMENT '联系人',
  `contact_phone` varchar(255) DEFAULT NULL COMMENT '联系电话',
  `supplier_email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `supplier_address` varchar(255) DEFAULT NULL COMMENT '地址',
  `bank_name` varchar(255) DEFAULT NULL COMMENT '开户银行',
  `bank_account` varchar(255) DEFAULT NULL COMMENT '银行账号',
  `tax_number` varchar(255) DEFAULT NULL COMMENT '税号',
  `credit_rating` float DEFAULT NULL COMMENT '信用评级',
  `status` varchar(50) DEFAULT NULL COMMENT '状态：active-启用, inactive-禁用',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `supplier_name` (`supplier_name`)
) ENGINE=MyISAM AUTO_INCREMENT=21 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `system_settings`
--

DROP TABLE IF EXISTS `system_settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `system_settings` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `code` varchar(255) DEFAULT NULL COMMENT '配置编码',
  `name` varchar(255) DEFAULT NULL COMMENT '配置名称',
  `value` text COMMENT '配置值（JSON格式存储复杂配置）',
  `type` varchar(50) DEFAULT NULL COMMENT '配置类型（如：setting, feature_flag, system）',
  `description` varchar(500) DEFAULT NULL COMMENT '描述',
  `status` varchar(50) DEFAULT NULL COMMENT '状态：active-启用, inactive-禁用',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `transaction`
--

DROP TABLE IF EXISTS `transaction`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `transaction` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `transaction_time` datetime NOT NULL COMMENT '交易时间',
  `transaction_type` varchar(20) NOT NULL COMMENT '交易类型: 收入/支出',
  `counterparty` varchar(100) DEFAULT NULL COMMENT '交易对方',
  `amount` decimal(15,4) DEFAULT NULL COMMENT '交易金额',
  `category` varchar(100) DEFAULT NULL COMMENT '交易分类',
  `description` varchar(500) DEFAULT NULL COMMENT '交易描述',
  `source` varchar(50) DEFAULT NULL COMMENT '交易来源: 微信/支付宝/银行卡等',
  `source_bill_no` varchar(100) DEFAULT NULL COMMENT '来源账单编号',
  `payment_method` varchar(50) DEFAULT NULL COMMENT '支付方式: 零钱/储蓄卡/信用卡等',
  `status` varchar(20) DEFAULT NULL COMMENT '状态',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  `created_by` varchar(20) DEFAULT NULL COMMENT '创建人',
  `updated_by` varchar(20) DEFAULT NULL COMMENT '更新人',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=101 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `user`
--

DROP TABLE IF EXISTS `user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(255) DEFAULT NULL COMMENT '用户名',
  `password` varchar(255) DEFAULT NULL COMMENT '密码',
  `phone` varchar(100) DEFAULT NULL COMMENT '电话',
  `age` float DEFAULT NULL COMMENT '年龄',
  `gender` varchar(50) DEFAULT NULL COMMENT '性别',
  `address` varchar(255) DEFAULT NULL COMMENT '地址',
  `email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `tag` varchar(255) DEFAULT NULL COMMENT '标签（控制采购、销售、凭证数据范围）：admin-管理员-全部，purchaseManage-采购-可查看采购数据，saleManage-销售-可查看销售数据，voucherManage-凭证-可查看凭证数据',
  `status` varchar(255) DEFAULT NULL COMMENT '状态：active-启用, inactive-禁用',
  `remark` varchar(255) DEFAULT NULL COMMENT '备注',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `updated_by` varchar(255) DEFAULT NULL COMMENT '更新者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=MyISAM AUTO_INCREMENT=16 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `user_operation_log`
--

DROP TABLE IF EXISTS `user_operation_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user_operation_log` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) DEFAULT NULL COMMENT '操作用户ID',
  `username` varchar(255) DEFAULT NULL COMMENT '操作用户名',
  `action_type` varchar(100) DEFAULT NULL COMMENT '操作类型：login/logout/create/update/delete/view',
  `module` varchar(255) DEFAULT NULL COMMENT '操作模块',
  `action` varchar(255) DEFAULT NULL COMMENT '具体操作',
  `ip_address` varchar(100) DEFAULT NULL COMMENT 'IP地址',
  `user_agent` text COMMENT '用户代理',
  `request_params` text COMMENT '请求参数',
  `response_result` text COMMENT '响应结果',
  `status` varchar(50) DEFAULT NULL COMMENT '操作状态：success-成功, fail-失败',
  `error_msg` text COMMENT '错误信息',
  `created_at` datetime DEFAULT NULL COMMENT '操作时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=13 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `user_role`
--

DROP TABLE IF EXISTS `user_role`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user_role` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) DEFAULT NULL COMMENT '用户ID',
  `role_id` int(11) DEFAULT NULL COMMENT '角色ID',
  `created_by` varchar(255) DEFAULT NULL COMMENT '创建者',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  PRIMARY KEY (`id`)
) ENGINE=MyISAM AUTO_INCREMENT=16 DEFAULT CHARSET=utf8;